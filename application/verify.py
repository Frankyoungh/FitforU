# application/verify.py
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

# ===== 数据结构 =====
class Level(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"

@dataclass
class Issue:
    level: Level
    code: str
    message: str
    where: Dict[str, Any]           # 定位信息：day/title/idx 等
    fix: Optional[Dict[str, Any]] = None  # 给出建议修复（可选）

@dataclass
class VerifyResult:
    ok: bool
    issues: List[Issue]
    counts: Dict[str, int]
    fixed_actions: Optional[List[Dict[str, Any]]] = None  # 若做了自动修复，给出修复版 actions

# ===== 工具函数 =====
def _parse_hhmm(s: str) -> datetime:
    # 仅用于比较，日期随便给同一天
    return datetime(2000, 1, 1, int(s[0:2]), int(s[3:5]))

def _duration_min(a: Dict[str, Any]) -> int:
    d = a.get("duration_min")
    if isinstance(d, (int, float)) and d > 0:
        return int(d)
    # 若没有 duration_min 且有 start/end，则计算
    st, ed = a.get("start"), a.get("end")
    if isinstance(st, str) and isinstance(ed, str) and len(st) >= 5 and len(ed) >= 5:
        return int((_parse_hhmm(ed) - _parse_hhmm(st)).total_seconds() // 60)
    return 0

def _copy_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(x) for x in actions]

# ===== 核心校验 =====
def verify_actions(actions: List[Dict[str, Any]], profile: Optional[Dict[str, Any]]=None) -> VerifyResult:
    issues: List[Issue] = []

    if not actions:
        return VerifyResult(ok=False, issues=[Issue(Level.ERROR, "EMPTY", "没有可执行的事件", {})],
                            counts={"ERROR":1,"WARNING":0,"INFO":0}, fixed_actions=[])

    # 1) 基础字段 & 合法范围
    for i, a in enumerate(actions):
        where = {"idx": i, "title": a.get("title"), "day": a.get("day"), "date": a.get("date")}
        if not a.get("title"):
            issues.append(Issue(Level.ERROR, "MISSING_TITLE", "缺少标题", where))
        day = a.get("day")
        if not isinstance(day, int) or day < 1:
            issues.append(Issue(Level.ERROR, "BAD_DAY", f"非法的 day：{day}", where))
        # 粗略识别潜在用药词（安全兜底）
        txt = (a.get("title") or "") + " " + (a.get("desc") or "")
        for kw in ("mg", "毫升", "剂量", "处方", "处方药"):
            if kw in txt:
                issues.append(Issue(Level.ERROR, "MED_RISK", f"检测到疑似用药敏感词：{kw}", where))

        dur = _duration_min(a)
        if dur <= 0:
            issues.append(Issue(Level.INFO, "NO_DURATION", "未提供时长（duration_min 或 start/end）", where))

    # 2) 同日时间冲突检测（需要 start/end）
    # 仅在存在 start/end 时做冲突检查
    has_time = all(isinstance(x.get("start"), str) and isinstance(x.get("end"), str) for x in actions)
    fixed = _copy_actions(actions)
    if has_time:
        # 按 (date, start) 排序
        fixed.sort(key=lambda x: (str(x.get("date")), str(x.get("start"))))
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for a in fixed:
            grouped.setdefault(str(a.get("date")), []).append(a)

        for date_key, day_list in grouped.items():
            last_end: Optional[datetime] = None
            for j, a in enumerate(day_list):
                st = _parse_hhmm(a["start"])
                ed = _parse_hhmm(a["end"])
                if ed <= st:
                    issues.append(Issue(Level.ERROR, "BAD_TIME", "end 早于/等于 start", {"date":date_key, "title":a.get("title")}))
                    continue
                if last_end and st < last_end:
                    # 冲突：顺延该事件到 last_end 开始，保持原时长
                    shift_min = int((last_end - st).total_seconds() // 60)
                    new_st = last_end
                    new_ed = new_st + (ed - st)
                    a["start"] = f"{new_st.hour:02d}:{new_st.minute:02d}"
                    a["end"]   = f"{new_ed.hour:02d}:{new_ed.minute:02d}"
                    issues.append(Issue(
                        Level.WARNING, "OVERLAP_SHIFT",
                        f"与同日上一事件冲突，已自动顺延 {shift_min} 分钟",
                        {"date": date_key, "title": a.get("title")},
                        fix={"start": a["start"], "end": a["end"]}
                    ))
                last_end = _parse_hhmm(a["end"])

    # 3) 当日总时长超阈（例如 > 120min）给 Warning
    per_day: Dict[str, int] = {}
    for a in fixed:
        key = str(a.get("date") or a.get("day"))
        per_day[key] = per_day.get(key, 0) + _duration_min(a)
    for k, total in per_day.items():
        if total > 120:
            issues.append(Issue(Level.WARNING, "VOLUME_HIGH", f"单日总时长 {total} 分钟，建议 ≤ 120 分钟", {"day_or_date": k}))

    # 汇总
    cnt = {"ERROR":0, "WARNING":0, "INFO":0}
    for it in issues:
        cnt[it.level] += 1
    ok = cnt["ERROR"] == 0

    return VerifyResult(ok=ok, issues=issues, counts=cnt, fixed_actions=fixed if has_time else None)

# =====（可选）对草案先做静态检查 =====
def verify_draft(draft: Dict[str, Any]) -> VerifyResult:
    issues: List[Issue] = []

    modules = draft.get("modules") or []
    horizon = draft.get("horizon_days")
    t_windows = draft.get("time_windows") or []

    if not modules:
        issues.append(Issue(Level.ERROR, "EMPTY_MODULES", "计划草案没有 modules", {}))

    if not isinstance(horizon, int) or horizon <= 0:
        issues.append(Issue(Level.INFO, "NO_HORIZON", "未设置 horizon_days，默认 7", {}))

    # time_windows 结构校验
    for ti, tw in enumerate(t_windows):
        if not isinstance(tw, dict) or "start" not in tw or "end" not in tw:
            issues.append(Issue(Level.WARNING, "BAD_TIME_WINDOW",
                                "time_windows 元素建议为 {'label','start','end'}",
                                {"idx": ti, "value": str(tw)}))

    # modules 逐条校验
    # modules 逐条校验
    allowed_tag_ids = {
        # 原有
        "hydration", "sleep", "mealprep", "protein",
        "fitness", "nutrition", "lifestyle", "rehab",
        # Planner 中实际使用的标签（保持同步，避免刷 UNKNOWN_TAG）
        "habit", "gym",
        "upper", "lower", "push", "pull", "legs",
        "cardio", "recovery",
        "log", "macro",          # 营养计划：记录 / 宏量
        "mobility",              # 康复 / 活动度
    }

    for i, m in enumerate(modules):
        where = {"idx": i, "day": m.get("day"), "title": m.get("title")}

        if not m.get("title"):
            issues.append(Issue(Level.ERROR, "MISSING_TITLE", "缺少标题", where))

        day = m.get("day")
        if not isinstance(day, int) or day < 1 or (isinstance(horizon, int) and day > horizon):
            issues.append(Issue(Level.ERROR, "BAD_DAY", f"非法的 day：{day}", where))

        dur = m.get("duration_min") or m.get("duration")
        if not isinstance(dur, (int, float)) or dur <= 0:
            issues.append(Issue(Level.INFO, "NO_DURATION", "未提供时长（duration_min/duration）", where))

        tags = m.get("tags") or m.get("labels")
        if not tags:
            issues.append(Issue(Level.INFO, "NO_TAGS", "未提供标签（tags/labels）", where))
        else:
            ids: List[str] = []
            if isinstance(tags, dict):
                if tags.get("id"):
                    ids = [tags["id"]]
            elif isinstance(tags, (list, tuple)):
                for t in tags:
                    if isinstance(t, dict) and t.get("id"):
                        ids.append(t["id"])
                    else:
                        ids.append(str(t))
            else:
                ids = [str(tags)]

            for tid in ids:
                if tid not in allowed_tag_ids:
                    issues.append(Issue(Level.INFO, "UNKNOWN_TAG", f"未识别标签：{tid}", where))


    cnt = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for it in issues:
        cnt[it.level] += 1  # Level 继承自 str，可直接当键

    return VerifyResult(ok=cnt["ERROR"] == 0, issues=issues, counts=cnt, fixed_actions=None)
