# ========== application/composer.py ==========
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import os, json

from .profile import Profile

# 默认模板；若存在 configs/templates.json 会自动合并覆盖
_DEFAULT_TEMPLATES = {
  "habit:hydration": {"muscle_group":"none", "default_min":10, "priority":3},
  "habit:sleep": {"muscle_group":"none", "default_min":30, "priority":3},
  "gym:upper:push": {"muscle_group":"upper_push", "default_min":60, "priority":1},
  "gym:upper:pull": {"muscle_group":"upper_pull", "default_min":60, "priority":1},
  "gym:lower:legs": {"muscle_group":"legs", "default_min":60, "priority":1},
  "recovery:stretch": {"muscle_group":"recovery", "default_min":20, "priority":2},
  "core": {"muscle_group":"core", "default_min":20, "priority":2},
  "nutrition:prep": {"muscle_group":"none", "default_min":60, "priority":2},
  "general": {"muscle_group":"none", "default_min":45, "priority":3}
}

def _load_templates() -> Dict[str, Dict[str, Any]]:
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "configs", "templates.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                merged = dict(_DEFAULT_TEMPLATES)
                merged.update(data)
                return merged
    except Exception:
        pass
    return dict(_DEFAULT_TEMPLATES)

_TEMPLATES = _load_templates()


def _tag_key(title: str, tags: List[str]) -> str:
    t = " ".join([title or "", *(tags or [])]).lower()
    if any(k in t for k in ["push","胸","三头","上肢推"]): return "gym:upper:push"
    if any(k in t for k in ["pull","背","二头","上肢拉"]): return "gym:upper:pull"
    if any(k in t for k in ["腿","下肢","squat","deadlift"]): return "gym:lower:legs"
    if any(k in t for k in ["stretch","拉伸","恢复"]): return "recovery:stretch"
    if any(k in t for k in ["core","腹","平板支撑"]): return "core"
    if any(k in t for k in ["补水","饮水","水分","hydration"]): return "habit:hydration"
    if any(k in t for k in ["睡眠","blue light","蓝光"]): return "habit:sleep"
    if any(k in t for k in ["备餐","餐前准备","meal prep","prep"]): return "nutrition:prep"
    return "general"


def _parse_hhmm(s: str) -> datetime:
    return datetime(2000,1,1,int(s[:2]),int(s[3:5]))

def _minutes_between(a: str, b: str) -> int:
    return int((_parse_hhmm(b) - _parse_hhmm(a)).total_seconds() // 60)

def _add_minutes(hhmm: str, mins: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = h*60 + m + int(mins)
    return f"{(total//60)%24:02d}:{total%60:02d}"

def _weekday_1_7(d: date) -> int:
    return (d.weekday() + 1)  # Monday=1 ... Sunday=7

@dataclass
class _Placed:
    date: date
    start: str
    end: str


def _day_windows(d: date, profile: Profile) -> List[Tuple[str,str,str]]:
    wd = _weekday_1_7(d)
    out: List[Tuple[str,str,str]] = []
    for tw in profile.time_windows:
        if wd in tw.days:
            out.append((tw.label, tw.start[:5], tw.end[:5]))
    return out


def _first_fit_slot(day: date, dur_min: int, used_blocks: List[Tuple[str,str]], profile: Profile) -> Optional[Tuple[str,str]]:
    windows = _day_windows(day, profile)
    for _, w_start, w_end in windows:
        cursor = w_start
        for s,e in sorted(used_blocks, key=lambda x: x[0]):
            # 排除和本窗口无交集的块
            if s >= w_end or e <= w_start:
                continue
            # gap 在 cursor→s 之间
            if _minutes_between(cursor, s) >= dur_min:
                return (cursor, _add_minutes(cursor, dur_min))
            # 向后推进
            if e > cursor:
                cursor = e
        # 尾部 gap
        if _minutes_between(cursor, w_end) >= dur_min:
            return (cursor, _add_minutes(cursor, dur_min))
    return None


def _muscle_ready(mg: str, day_index_1based: int, last_hit_day: Dict[str,int], profile: Profile) -> bool:
    if mg in ("none", "recovery"):
        return True
    need_h = int(profile.min_muscle_gap_h.get(mg, 48))
    need_d = (need_h + 23) // 24
    last = last_hit_day.get(mg, -10**6)
    return (day_index_1based - last) >= need_d


def compose_plan(draft: Dict[str, Any], profile: Profile, start_date: date) -> List[Dict[str, Any]]:
    """
    PlanDraft → actions：按个人可用时段/阈值进行排程。
    规则：
      * 按 day 升序 + priority 升序 排序放置
      * 仅使用 profile.time_windows 指定的钟点/周日
      * 单日总分钟数 ≤ profile.max_daily_minutes
      * 肌群最小间隔（小时→天）
      * unavailable_dates 跳过；放不下则顺延到下一个可用日
    """
    modules = draft.get("modules") or []

    # 1) 归一化：决定模板、肌群、时长、优先级
    items: List[Dict[str, Any]] = []
    for i, m in enumerate(modules, 1):
        title = m.get("title") or m.get("name") or f"Module {i}"
        tags  = m.get("tags") or m.get("labels") or []
        key   = _tag_key(title, tags if isinstance(tags, list) else [str(tags)])
        tpl   = _TEMPLATES.get(key, _TEMPLATES["general"])
        dur   = int(m.get("duration_min") or m.get("duration") or tpl["default_min"])
        prio  = int(m.get("priority") or tpl["priority"])
        mg    = m.get("muscle_group") or tpl["muscle_group"]
        day   = int(m.get("day") or i)
        desc  = m.get("desc") or m.get("description") or ""
        items.append({
            "day": day, "title": title, "tags": tags, "duration_min": dur,
            "priority": prio, "muscle_group": mg, "desc": desc
        })
    items.sort(key=lambda x: (x["day"], x["priority"]))

    # 2) 放置
    actions: List[Dict[str, Any]] = []
    used_minutes_by_date: Dict[str, int] = {}
    used_blocks_by_date: Dict[str, List[Tuple[str,str]]] = {}
    last_hit_day: Dict[str, int] = {}

    horizon = int(draft.get("horizon_days", 7))
    max_daily = int(profile.max_daily_minutes)

    for it in items:
        nominal_offset = max(0, it["day"] - 1)
        placed: Optional[_Placed] = None
        # 最多顺延 horizon+7 天避免死循环
        for shift in range(0, horizon + 7):
            idx = nominal_offset + shift
            d = start_date + timedelta(days=idx)
            d_str = d.strftime("%Y-%m-%d")
            if d_str in (profile.unavailable_dates or []):
                continue
            if not _muscle_ready(it["muscle_group"], idx+1, last_hit_day, profile):
                continue
            used_today = used_minutes_by_date.get(d_str, 0)
            if used_today >= max_daily:
                continue
            slot = _first_fit_slot(d, it["duration_min"], used_blocks_by_date.get(d_str, []), profile)
            if slot is None:
                continue
            st, ed = slot
            if used_today + it["duration_min"] > max_daily:
                continue
            placed = _Placed(d, st, ed)
            used_minutes_by_date[d_str] = used_today + it["duration_min"]
            used_blocks_by_date.setdefault(d_str, []).append((st, ed))
            last_hit_day[it["muscle_group"]] = idx+1
            break

        if placed is None:
            # 兜底：塞到最后一天能放的位置（仍遵守窗口，放不下就 21:00 起）
            d = start_date + timedelta(days=horizon-1)
            d_str = d.strftime("%Y-%m-%d")
            slot = _first_fit_slot(d, it["duration_min"], used_blocks_by_date.get(d_str, []), profile)
            if slot:
                st, ed = slot
            else:
                st, ed = "21:00", _add_minutes("21:00", it["duration_min"])
            actions.append({
                "title": it["title"], "desc": it["desc"], "tags": it["tags"],
                "day": horizon, "date": d_str, "duration_min": it["duration_min"],
                "start": st, "end": ed, "priority": it["priority"], "muscle_group": it["muscle_group"]
            })
            continue

        actions.append({
            "title": it["title"], "desc": it["desc"], "tags": it["tags"],
            "day": (placed.date - start_date).days + 1,
            "date": placed.date.strftime("%Y-%m-%d"),
            "duration_min": it["duration_min"],
            "start": placed.start, "end": placed.end,
            "priority": it["priority"], "muscle_group": it["muscle_group"]
        })

    return actions