# # -*- coding: utf-8 -*-
# from __future__ import annotations
#
# """
# Step 2 - Planner (生成计划草案)
#
# 职责：
# - 根据 user_input + agent_config + (可选) memory/profile
#   生成结构化计划草案（PlanDraft 或等价 dict）。
# - 不直接做具体日程排程（那是后续 Composer/ACT 的事），
#   但会输出 horizon_days / modules / time_windows 等草案信息。
#
# 要点：
# - 支持 plan_types / horizon_days（来自侧栏配置）
# - 根据用户输入推断补充 plan_types
# - 利用 memory.profile 的长期偏好：
#     - time_windows 用于 summary 和下游排程提示
#     - max_daily_minutes 用于限制当日总训练时长
# """
#
# from dataclasses import asdict, is_dataclass
# from typing import Any, Dict, List, Optional
# import random
# import re
#
# from .schemas import PlanDraft, TimeWindow, DEFAULT_WINDOWS
#
# # 允许的 plan_types
# ALLOWED_TYPES = {"lifestyle", "fitness", "nutrition", "rehab"}
#
# # 文本触发提示 -> plan_type
# PLAN_TYPE_HINTS = [
#     (["健身", "gym", "力量", "举重", "肌力", "塑形", "训练"], "fitness"),
#     (["减脂", "脂肪", "体重", "饮食", "卡路里", "热量", "营养", "配餐", "备餐"], "nutrition"),
#     (["康复", "拉伸", "理疗", "肩", "颈", "腰", "膝", "术后", "恢复"], "rehab"),
#     (["睡眠", "作息", "补水", "喝水", "步数", "走路", "久坐", "压力", "节律"], "lifestyle"),
# ]
#
# # ---------------------------------------------------------------------
# # 小工具
# # ---------------------------------------------------------------------
#
# def _extract_keywords(text: str, limit: int = 24) -> List[str]:
#     """从用户输入里抽一批关键词，后面 rehab 等可以用。"""
#     if not text:
#         return []
#     tokens = re.findall(r"[\u4e00-\u9fa5]{1,}|[A-Za-z]{2,}", text)
#     seen = set()
#     out: List[str] = []
#     for t in tokens:
#         if t not in seen:
#             seen.add(t)
#             out.append(t)
#         if len(out) >= limit:
#             break
#     return out
#
#
# def _infer_types_from_text(text: str) -> List[str]:
#     """根据用户输入粗略猜测 plan_types。"""
#     if not text:
#         return []
#     res: List[str] = []
#     low = text.lower()
#     for keys, t in PLAN_TYPE_HINTS:
#         if any(k.lower() in low for k in keys):
#             if t not in res:
#                 res.append(t)
#     return res
#
#
# def _pick_plan_types(user_input: str, agent_config: Dict[str, Any]) -> List[str]:
#     """
#     合并：
#     - 侧栏配置里的 plan_types
#     - 从文本中推断的 plan_types
#     """
#     cfg_types = agent_config.get("plan_types") or []
#     if isinstance(cfg_types, str):
#         cfg_types = [cfg_types]
#     cfg_types = [str(x).lower() for x in cfg_types]
#
#     text_types = _infer_types_from_text(user_input)
#
#     merged: List[str] = []
#     for t in cfg_types + text_types:
#         t = str(t).lower()
#         if t in ALLOWED_TYPES and t not in merged:
#             merged.append(t)
#
#     if not merged:
#         merged = ["lifestyle"]
#     return merged
#
#
# def _pick_horizon_days(agent_config: Dict[str, Any]) -> int:
#     """从 agent_config 读 horizon_days，并做安全裁剪。"""
#     try:
#         h = int(agent_config.get("horizon_days") or 7)
#     except Exception:
#         h = 7
#     return max(1, min(h, 60))
#
#
# def _tw_from_dict(d: Dict[str, Any]) -> TimeWindow:
#     """把 dict 转为 TimeWindow，只保留 label/start/end。"""
#     label = str(d.get("label") or "evening")
#     start = str(d.get("start") or "19:00")[:5]
#     end = str(d.get("end") or "22:00")[:5]
#     return TimeWindow(label=label, start=start, end=end)
#
#
# def _derive_time_windows(
#     agent_config: Dict[str, Any],
#     memory: Optional[Dict[str, Any]],
# ) -> List[TimeWindow]:
#     """
#     time_windows 优先级：
#     1) agent_config.time_windows
#     2) memory.profile.time_windows
#     3) DEFAULT_WINDOWS（schemas 里给的默认值）
#     4) fallback: evening 19:00–22:00
#     """
#     # 1) agent_config
#     tw_cfg = agent_config.get("time_windows")
#     if isinstance(tw_cfg, list) and tw_cfg:
#         out: List[TimeWindow] = []
#         for item in tw_cfg:
#             if isinstance(item, TimeWindow):
#                 out.append(item)
#             elif isinstance(item, dict):
#                 out.append(_tw_from_dict(item))
#         if out:
#             return out
#
#     # 2) memory.profile
#     if memory:
#         prof = (
#             memory.get("profile")
#             or memory.get("PROFILE")
#             or memory.get("user_profile")
#         )
#         if isinstance(prof, Dict):
#             tws = prof.get("time_windows") or []
#             out: List[TimeWindow] = []
#             for item in tws:
#                 if isinstance(item, TimeWindow):
#                     out.append(item)
#                 elif isinstance(item, dict):
#                     out.append(_tw_from_dict(item))
#             if out:
#                 return out
#
#     # 3) 默认
#     if DEFAULT_WINDOWS:
#         return [
#             TimeWindow(label=w.label, start=w.start, end=w.end)
#             for w in DEFAULT_WINDOWS
#         ]
#
#     # 4) fallback
#     return [TimeWindow(label="evening", start="19:00", end="22:00")]
#
#
# def _get_max_daily_minutes(
#     agent_config: Dict[str, Any],
#     memory: Optional[Dict[str, Any]],
# ) -> Optional[int]:
#     """
#     最大单日分钟：
#     1) agent_config.max_daily_minutes
#     2) memory.profile.max_daily_minutes
#     """
#     cand = agent_config.get("max_daily_minutes")
#     if cand:
#         try:
#             return max(15, int(cand))
#         except Exception:
#             pass
#
#     if memory:
#         prof = (
#             memory.get("profile")
#             or memory.get("PROFILE")
#             or memory.get("user_profile")
#         )
#         if isinstance(prof, Dict):
#             cand = prof.get("max_daily_minutes")
#             if cand:
#                 try:
#                     return max(15, int(cand))
#                 except Exception:
#                     pass
#
#     return None
#
#
# def _add_module(
#     modules: List[Dict[str, Any]],
#     day_minutes: Dict[int, int],
#     max_daily: Optional[int],
#     *,
#     day: int,
#     title: str,
#     tags: List[str],
#     duration_min: int,
#     desc: str = "",
# ) -> None:
#     """统一封装模块添加逻辑，顺带控制单日总时长。"""
#     if day < 1:
#         day = 1
#     duration_min = int(duration_min)
#
#     # 单日上限保护
#     if max_daily:
#         used = day_minutes.get(day, 0)
#         if used + duration_min > max_daily:
#             return
#
#     mod = {
#         "day": int(day),
#         "title": title,
#         "tags": list(tags),
#         "duration_min": duration_min,
#     }
#     if desc:
#         mod["desc"] = desc
#
#     modules.append(mod)
#
#     if max_daily:
#         day_minutes[day] = day_minutes.get(day, 0) + duration_min
#
# # ---------------------------------------------------------------------
# # 各类型模板：完全 rule-based，可审计、可调参
# # ---------------------------------------------------------------------
#
# def _build_lifestyle_modules(horizon, kw, modules, day_minutes, max_daily):
#     for d in range(1, horizon + 1):
#         _add_module(
#             modules, day_minutes, max_daily,
#             day=d,
#             title="补水 + 轻活动 10′",
#             tags=["lifestyle", "habit", "hydration"],
#             duration_min=10,
#             desc="随手水杯，每小时起身走动 2-3 分钟，减少久坐。",
#         )
#         if d % 2 == 1:
#             _add_module(
#                 modules, day_minutes, max_daily,
#                 day=d,
#                 title="睡前放松与电子产品下线 20′",
#                 tags=["lifestyle", "sleep"],
#                 duration_min=20,
#                 desc="睡前 30 分钟远离手机/电脑，做伸展或呼吸练习，稳定作息。",
#             )
#
#
# def _build_fitness_modules(horizon, modules, day_minutes, max_daily):
#     for d in range(1, horizon + 1):
#         slot = (d - 1) % 4
#         if slot == 0:
#             _add_module(
#                 modules, day_minutes, max_daily,
#                 day=d,
#                 title="上肢推训练 45′",
#                 tags=["fitness", "gym", "upper", "push"],
#                 duration_min=45,
#                 desc="俯卧撑/卧推/肩推为主，自身体重或中等负重。",
#             )
#         elif slot == 1:
#             _add_module(
#                 modules, day_minutes, max_daily,
#                 day=d,
#                 title="下肢力量训练 45′",
#                 tags=["fitness", "gym", "lower", "legs"],
#                 duration_min=45,
#                 desc="深蹲/弓步/硬拉变式，注意动作质量。",
#             )
#         elif slot == 2:
#             _add_module(
#                 modules, day_minutes, max_daily,
#                 day=d,
#                 title="上肢拉训练 40′",
#                 tags=["fitness", "gym", "upper", "pull"],
#                 duration_min=40,
#                 desc="划船/下拉/反向飞鸟，均匀发力，保护下背。",
#             )
#         else:
#             _add_module(
#                 modules, day_minutes, max_daily,
#                 day=d,
#                 title="低强度有氧或主动恢复 30′",
#                 tags=["fitness", "cardio", "recovery"],
#                 duration_min=30,
#                 desc="快走/椭圆/单车，舒适心率，帮助恢复。",
#             )
#
#
# def _build_nutrition_modules(horizon, modules, day_minutes, max_daily):
#     for d in range(1, horizon + 1):
#         if d == 1:
#             _add_module(
#                 modules, day_minutes, max_daily,
#                 day=d,
#                 title="基础饮食记录 20′",
#                 tags=["nutrition", "log"],
#                 duration_min=20,
#                 desc="记录全天饮食，不做剧烈调整，只看真实习惯。",
#             )
#         elif d == 2:
#             _add_module(
#                 modules, day_minutes, max_daily,
#                 day=d,
#                 title="设定能量与蛋白目标 20′",
#                 tags=["nutrition", "macro"],
#                 duration_min=20,
#                 desc="根据体重和目标估算大致能量/蛋白范围，形成简单原则。",
#             )
#         else:
#             _add_module(
#                 modules, day_minutes, max_daily,
#                 day=d,
#                 title="今日餐盘检查 10′",
#                 tags=["nutrition", "habit"],
#                 duration_min=10,
#                 desc="检查：足够蛋白+多蔬菜+少含糖饮料+少高度加工。",
#             )
#
#
# def _build_rehab_modules(horizon, kw, modules, day_minutes, max_daily):
#     text = "".join(kw)
#     if any(k in text for k in ["颈", "肩"]):
#         target = "neck_shoulder"
#     elif any(k in text for k in ["腰", "背"]):
#         target = "lumbar"
#     elif any(k in text for k in ["膝", "腿"]):
#         target = "knee"
#     else:
#         target = "general"
#
#     for d in range(1, horizon + 1):
#         if target == "neck_shoulder":
#             title = "颈肩放松与姿势训练 15′"
#             desc = "颈部侧屈/旋转、肩胛收缩等温和动作，无明显疼痛为准。"
#         elif target == "lumbar":
#             title = "腰背活动度+核心激活 15′"
#             desc = "猫牛式、桥式、死虫等低强度动作，以舒适为前提。"
#         elif target == "knee":
#             title = "膝周肌群激活 15′"
#             desc = "直腿抬高、小幅深蹲等，避免疼痛角度。"
#         else:
#             title = "全身温和拉伸 15′"
#             desc = "覆盖主要关节的轻柔拉伸，配合呼吸。"
#
#         _add_module(
#             modules, day_minutes, max_daily,
#             day=d,
#             title=title,
#             tags=["rehab", "mobility"],
#             duration_min=15,
#             desc=desc,
#         )
#
# # ---------------------------------------------------------------------
# # 对外主函数
# # ---------------------------------------------------------------------
#
# def draft_plan(
#     user_input: str,
#     agent_config: Dict[str, Any],
#     memory: Optional[Dict[str, Any]] = None,
# ) -> Any:
#     """
#     核心入口：
#     - 选择 plan_types
#     - 确定 horizon_days
#     - 从 memory/profile 推导 time_windows & max_daily_minutes
#     - 按 plan_types 组合 rule-based modules
#     """
#     text = (user_input or "").strip()
#     agent_config = agent_config or {}
#     memory = memory or {}
#
#     kw = _extract_keywords(text)
#     plan_types = _pick_plan_types(text, agent_config)
#     horizon = _pick_horizon_days(agent_config)
#     time_windows = _derive_time_windows(agent_config, memory)
#     max_daily = _get_max_daily_minutes(agent_config, memory)
#
#     # 预留随机性（当前模板没用 rnd，如果之后要做随机模块可以用）
#     rnd = random.Random()
#     if agent_config.get("deterministic"):
#         try:
#             seed = int(agent_config.get("seed", 42))
#         except Exception:
#             seed = 42
#         rnd.seed(seed)
#
#     modules: List[Dict[str, Any]] = []
#     day_minutes: Dict[int, int] = {}
#
#     if "lifestyle" in plan_types:
#         _build_lifestyle_modules(horizon, kw, modules, day_minutes, max_daily)
#     if "fitness" in plan_types:
#         _build_fitness_modules(horizon, modules, day_minutes, max_daily)
#     if "nutrition" in plan_types:
#         _build_nutrition_modules(horizon, modules, day_minutes, max_daily)
#     if "rehab" in plan_types:
#         _build_rehab_modules(horizon, kw, modules, day_minutes, max_daily)
#
#     # 兜底：保证至少有一个模块
#     if not modules:
#         _add_module(
#             modules, day_minutes, max_daily,
#             day=1,
#             title="温和启程：5′ 呼吸 + 10′ 散步",
#             tags=["lifestyle"],
#             duration_min=15,
#             desc="从非常简单的动作开始，观察身体反应再逐步升级计划。",
#         )
#
#     tw_desc = ", ".join([f"{w.label} {w.start}-{w.end}" for w in time_windows])
#     summary = (
#         f"本计划为 {horizon} 天预览，类型：{', '.join(plan_types)}；"
#         f"优先安排在：{tw_desc or '晚间时段'}。"
#         f" 所有建议均为一般性健康/训练建议，不替代线下诊疗。"
#     )
#
#     payload = {
#         "plan_types": plan_types,
#         "horizon_days": horizon,
#         "time_windows": [
#             {"label": w.label, "start": w.start, "end": w.end} for w in time_windows
#         ],
#         "constraints": {
#             "max_daily_minutes": max_daily,
#         },
#         "modules": modules,
#         "keywords": kw,
#         "summary": summary,
#     }
#
#     # 尝试用 PlanDraft 包一层，便于后续类型检查；失败就直接返回 dict
#     try:
#         return PlanDraft(**payload)
#     except Exception:
#         return payload

# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
from __future__ import annotations
import random
from dataclasses import dataclass, is_dataclass, asdict
from typing import List, Dict, Optional, Any
import re
from application.language_utils import detect_language

# -------------------------- 核心常量（还原原始多项目逻辑+标签合规）--------------------------
# 1. 计划类型触发关键词（中英双语）
PLAN_TYPE_HINTS = [
    (["健身", "gym", "力量", "举重", "肌力", "塑形", "训练",
      "workout", "strength training", "muscle building"], "fitness"),
    (["饮食", "热量", "营养", "蛋白质", "碳水", "脂肪",
      "diet", "nutrition", "calorie", "protein", "carb"], "nutrition"),
    (["康复", "拉伸", "理疗", "肌肉酸痛",
      "rehab", "recovery", "stretching", "muscle soreness"], "rehab"),
    (["睡眠", "作息", "补水", "步数", "久坐",
      "sleep", "hydration", "steps", "sedentary"], "lifestyle"),
]

# 2. 双语模板（还原原始多项目逻辑，标签仅用核心合规标签：fitness/nutrition/rehab/lifestyle）
BILINGUAL_TEMPLATES = {
    "fitness": {
        "zh": [
            # 上肢训练
            ("胸部训练 30′", "平板卧推12次×4组 + 上斜哑铃卧推10次×3组", ["fitness", "chest"]),
            ("背部训练 30′", "引体向上10次×4组（辅助） + 坐姿划船15次×3组", ["fitness", "back"]),
            ("肩部训练 25′", "哑铃肩推12次×3组 + 侧平举15次×3组", ["fitness", "shoulders"]),
            ("手臂训练 25′", "弯举12次×3组 + 三头肌下压15次×3组", ["fitness", "arms"]),

            # 下肢训练
            ("腿部训练 35′", "杠铃深蹲12次×4组 + 硬拉8次×3组", ["fitness", "legs"]),
            ("臀部训练 25′", "臀桥20次×4组 + 箭步蹲10次×3组/腿", ["fitness", "glutes"]),

            # 综合训练
            ("全身HIIT 20′", "波比跳30秒×4组 + 高抬腿30秒×4组（组间休30秒）", ["fitness", "hiit"]),
            ("循环训练 30′", " kettlebell摇摆15次 + 俯卧撑12次 + 登山跑30秒 循环4组", ["fitness", "circuit"]),

            # 轻量/恢复训练
            ("轻量有氧 25′", "慢跑或椭圆机，保持中等心率", ["fitness", "cardio"]),
            ("功能性训练 25′", "壶铃深蹲12次×3组 + 药球旋转15次×3组", ["fitness", "functional"]),
        ],
        "en": [
            # Upper Body
            ("Chest Training 30′", "Flat bench press 12×4 + Incline dumbbell press 10×3", ["fitness", "chest"]),
            ("Back Training 30′", "Pull-ups 10×4 (assisted) + Seated row 15×3", ["fitness", "back"]),
            ("Shoulder Training 25′", "Dumbbell shoulder press 12×3 + Lateral raises 15×3", ["fitness", "shoulders"]),
            ("Arm Training 25′", "Bicep curls 12×3 + Tricep dips 15×3", ["fitness", "arms"]),

            # Lower Body
            ("Leg Training 35′", "Barbell squats 12×4 + Deadlifts 8×3", ["fitness", "legs"]),
            ("Glute Training 25′", "Hip thrusts 20×4 + Lunges 10×3/leg", ["fitness", "glutes"]),

            # Full Body
            ("Full Body HIIT 20′", "Burpees 30s×4 + High knees 30s×4 (30s rest)", ["fitness", "hiit"]),
            ("Circuit Training 30′", "Kettlebell swings 15 + Push-ups 12 + Mountain climbers 30s (4 rounds)", ["fitness", "circuit"]),

            # Light/Recovery
            ("Light Cardio 25′", "Jogging or elliptical, moderate heart rate", ["fitness", "cardio"]),
            ("Functional Training 25′", "Kettlebell squats 12×3 + Medicine ball twists 15×3", ["fitness", "functional"]),
        ]
    },
    "nutrition": {
        "zh": [
            ("饮食记录 10′", "记录早中晚餐食物种类", ["nutrition"]),
            ("补水提醒 5′", "饮用300ml温水，设置定时提醒", ["nutrition"]),
            ("餐盘检查 5′", "确保每餐有蛋白+蔬菜", ["nutrition"]),
        ],
        "en": [
            ("Diet Log 10′", "Record breakfast/lunch/dinner food types", ["nutrition"]),
            ("Hydration Reminder 5′", "Drink 300ml warm water, set timer", ["nutrition"]),
            ("Meal Check 5′", "Ensure each meal has protein + vegetables", ["nutrition"]),
        ]
    },
    "lifestyle": {
        "zh": [
            ("久坐活动 5′", "起身拉伸/踮脚，活动腰椎", ["lifestyle"]),
            ("步数达标 10′", "完成2000步，利用碎片时间", ["lifestyle"]),
            ("睡前放松 10′", "远离电子设备，深呼吸", ["lifestyle"]),
        ],
        "en": [
            ("Sedentary Break 5′", "Stand and stretch, move lumbar spine", ["lifestyle"]),
            ("Step Goal 10′", "Complete 2000 steps with fragmented time", ["lifestyle"]),
            ("Pre-Sleep Relax 10′", "Avoid electronics, deep breathing", ["lifestyle"]),
        ]
    },
    "rehab": {
        "zh": [
            ("肌肉拉伸 15′", "滚动泡沫轴+静态拉伸", ["rehab"]),
            ("关节活动 10′", "缓慢活动肩颈/膝盖，避免僵硬", ["rehab"]),
        ],
        "en": [
            ("Muscle Stretching 15′", "Foam rolling + static stretching", ["rehab"]),
            ("Joint Mobility 10′", "Slowly move shoulders/neck/knees", ["rehab"]),
        ]
    }
}

# 3. 默认配置（还原原始逻辑：每日最大90分钟，3个时间窗口）
DEFAULT_HORIZON_DAYS = 7
DEFAULT_MAX_DAILY_MINUTES = 90  # 延长每日时长，容纳更多项目
TIME_WINDOW_DEFAULTS = [
    {"label": "morning", "start": "07:00", "end": "08:30"},  # 1.5小时窗口
    {"label": "noon", "start": "12:30", "end": "13:30"},  # 1小时窗口
    {"label": "evening", "start": "19:00", "end": "20:30"},  # 1.5小时窗口
]


# -------------------------- 数据类（不变）--------------------------
@dataclass
class TimeWindow:
    label: str
    start: str
    end: str


@dataclass
class PlanDraft:
    plan_types: List[str]
    horizon_days: int
    time_windows: List[Dict[str, str]]
    constraints: Dict[str, Any]
    modules: List[Dict[str, Any]]
    keywords: List[str]
    summary: str
    language: str
    memory: Optional[Dict[str, Any]] = None


# -------------------------- 辅助函数（还原原始简单逻辑）--------------------------
def _strip(text: str) -> str:
    if not text:
        return ""
    punc_pattern = re.compile(r'[^\u4e00-\u9fff\w\s]')
    return punc_pattern.sub('', text).strip()


def _extract_keywords(text: str) -> List[str]:
    text = _strip(text).lower()
    all_keywords = []
    for hints, _ in PLAN_TYPE_HINTS:
        all_keywords.extend(hints)
    matched = [kw for kw in all_keywords if kw.lower() in text]
    return list(dict.fromkeys(matched))[:10]


def _pick_plan_types(text: str, agent_config: Dict[str, Any]) -> List[str]:
    # text = _strip(text).lower()
    # config_types = agent_config.get("plan_types", [])
    # if config_types and isinstance(config_types, list):
    #     valid_types = ["fitness", "nutrition", "rehab", "lifestyle"]
    #     return [t.lower() for t in config_types if t.lower() in valid_types]
    #
    # picked = []
    # for hints, plan_type in PLAN_TYPE_HINTS:
    #     if any(hint.lower() in text for hint in hints) and plan_type not in picked:
    #         picked.append(plan_type)
    # return picked if picked else ["fitness", "lifestyle", "nutrition"]  # 默认多类型组合
    text = _strip(text).lower()
    config_types = agent_config.get("plan_types", [])
    valid_types = ["fitness", "nutrition", "rehab", "lifestyle"]

    # 处理配置中的类型
    if config_types and isinstance(config_types, list):
        filtered = [t.lower() for t in config_types if t.lower() in valid_types]
        # 如果配置中包含健身相关，确保保留
        if any(t == "fitness" for t in filtered):
            return filtered
        return filtered if filtered else ["fitness"]  # 配置无效时默认健身

    # 从文本推断类型
    picked = []
    for hints, plan_type in PLAN_TYPE_HINTS:
        if any(hint.lower() in text for hint in hints) and plan_type not in picked:
            picked.append(plan_type)

    # 确保健身优先：如果有健身相关关键词，优先保留
    if any(t == "fitness" for t in picked):
        return picked
    # 无明确类型时默认健身
    return picked if picked else ["fitness"]

def _pick_horizon_days(agent_config: Dict[str, Any]) -> int:
    horizon = agent_config.get("horizon_days")
    if isinstance(horizon, int) and 1 <= horizon <= 30:
        return horizon
    text = agent_config.get("user_input", "").lower()
    day_pattern = re.compile(r'(\d+)\s*(day|days|天)')
    match = day_pattern.search(text)
    return min(int(match.group(1)), 30) if match else DEFAULT_HORIZON_DAYS


def _time_to_minutes(time_str: str) -> int:
    try:
        hours, minutes = map(int, time_str.split(":"))
        return hours * 60 + minutes
    except Exception:
        return 0


def _minutes_to_time(minutes: int) -> str:
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


def _derive_time_windows(agent_config: Dict[str, Any], memory: Optional[Dict[str, Any]]) -> List[TimeWindow]:
    config_windows = agent_config.get("time_windows")
    if config_windows and isinstance(config_windows, list) and config_windows:
        try:
            return [TimeWindow(**win) for win in config_windows]
        except Exception:
            pass
    if memory and isinstance(memory.get("time_windows"), list):
        try:
            return [TimeWindow(**win) for win in memory["time_windows"]]
        except Exception:
            pass
    return [TimeWindow(**win) for win in TIME_WINDOW_DEFAULTS]


def _get_max_daily_minutes(agent_config: Dict[str, Any], memory: Optional[Dict[str, Any]]) -> int:
    if "max_daily_minutes" in agent_config and isinstance(agent_config["max_daily_minutes"], int) and agent_config[
        "max_daily_minutes"] > 0:
        return min(agent_config["max_daily_minutes"], 120)
    if memory and isinstance(memory.get("max_daily_minutes"), int) and memory["max_daily_minutes"] > 0:
        return min(memory["max_daily_minutes"], 120)
    return DEFAULT_MAX_DAILY_MINUTES


# -------------------------- 时间窗口分配（还原原始简单逻辑：优先填窗口，不限制项目数）--------------------------
def _add_module(
        modules: List[Dict[str, Any]],
        day_minutes: Dict[int, int],
        day_window_usage: Dict[int, Dict[str, int]],
        time_windows: List[TimeWindow],
        max_daily: int,
        day: int,
        title: str,
        tags: List[str],
        duration_min: int,
        desc: str,
) -> None:
    # 检查当日总时长是否超限
    current_total = day_minutes.get(day, 0)
    if current_total + duration_min > max_daily:
        return

    # 简单分配：找第一个能容纳的窗口（不管是否已有项目）
    assigned_window = None
    start_min = 0
    for tw in time_windows:
        tw_start = _time_to_minutes(tw.start)
        tw_end = _time_to_minutes(tw.end)
        used_end = day_window_usage[day][tw.label]
        if used_end + duration_min <= tw_end:
            assigned_window = tw
            start_min = used_end
            break

    if not assigned_window:
        return

    # 计算结束时间
    end_min = start_min + duration_min
    start_time = _minutes_to_time(start_min)
    end_time = _minutes_to_time(end_min)

    # 更新使用状态
    day_window_usage[day][assigned_window.label] = end_min
    day_minutes[day] = current_total + duration_min

    # 添加项目（标签仅核心合规标签）
    modules.append({
        "day": day,
        "title": title,
        "tags": tags,  # 仅 [fitness/nutrition/rehab/lifestyle]
        "duration_min": duration_min,
        "start_time": start_time,
        "end_time": end_time,
        "description": desc,
        "time_window_label": assigned_window.label,
    })


# -------------------------- normalize_draft（补全dataclass处理）--------------------------
def normalize_draft(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    try:
        from pydantic import BaseModel
    except Exception:
        BaseModel = None
    if BaseModel is not None and isinstance(obj, BaseModel):
        return obj.model_dump() if hasattr(obj, "model_dump") else obj.dict()
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "__dict__"):
        try:
            return dict(obj.__dict__)
        except Exception:
            pass
    try:
        return dict(obj)
    except Exception:
        return {"_repr": repr(obj)}


# -------------------------- 计划构建（还原原始多项目逻辑）--------------------------
def _build_modules(
        plan_type: str,
        horizon: int,
        modules: List[Dict[str, Any]],
        day_minutes: Dict[int, int],
        day_window_usage: Dict[int, Dict[str, int]],
        time_windows: List[TimeWindow],
        max_daily: int,
        lang: str,
) -> None:
    """还原原始逻辑：每天生成多个短项目，不限制数量（只要时长够）"""
    templates = BILINGUAL_TEMPLATES.get(plan_type, {}).get(lang, [])
    if not templates:
        return
    # 每天随机选2-3个短项目（还原原始多项目逻辑）
    for d in range(1, horizon + 1):
        # 随机选项目（避免每天重复，数量2-3个）
        num_items = random.randint(2, 3)
        selected_templates = random.sample(templates, min(num_items, len(templates)))
        for title, desc, tags in selected_templates:
            _add_module(
                modules, day_minutes, day_window_usage, time_windows, max_daily,
                day=d, title=title, tags=tags, duration_min=int(title.split("′")[0].split()[-1]),
                desc=desc
            )


# -------------------------- 主函数（还原原始多类型组合逻辑）--------------------------
def draft_plan(
        user_input: str,
        agent_config: Dict[str, Any],
        memory: Optional[Dict[str, Any]] = None,
        intent: Optional[str] = None,
) -> PlanDraft | Dict[str, Any]:
    user_input = (user_input or "").strip()
    agent_config = agent_config or {}
    memory = memory or {}
    lang = detect_language(user_input)
    kw = _extract_keywords(user_input)

    # 1. 确定计划类型（默认多类型组合，保证项目数量）
    plan_types = _pick_plan_types(user_input, agent_config)
    if intent:
        intent_type = intent.lower()
        if intent_type in ["fitness_gym", "fitness"] and "fitness" not in plan_types:
            plan_types.append("fitness")
        elif intent_type == "nutrition" and "nutrition" not in plan_types:
            plan_types.append("nutrition")
        elif intent_type == "rehab" and "rehab" not in plan_types:
            plan_types.append("rehab")
        elif intent_type == "lifestyle" and "lifestyle" not in plan_types:
            plan_types.append("lifestyle")
    plan_types = list(dict.fromkeys(plan_types))

    # 2. 基础配置
    horizon = _pick_horizon_days(agent_config)
    time_windows = _derive_time_windows(agent_config, memory)
    max_daily = _get_max_daily_minutes(agent_config, memory)

    # 3. 初始化数据
    modules: List[Dict[str, Any]] = []
    day_minutes: Dict[int, int] = {}
    day_window_usage: Dict[int, Dict[str, int]] = {
        day: {tw.label: _time_to_minutes(tw.start) for tw in time_windows}
        for day in range(1, horizon + 1)
    }

    # 4. 构建模块（每个类型都生成多个项目，保证数量）
    for plan_type in plan_types:
        _build_modules(plan_type, horizon, modules, day_minutes, day_window_usage, time_windows, max_daily, lang)

    # 5. 兜底（无项目时添加默认）
    if not modules:
        default_title = "基础活动 15′" if lang == "zh" else "Basic Activity 15′"
        default_desc = "散步+简单拉伸" if lang == "zh" else "Walking + simple stretching"
        _add_module(
            modules, day_minutes, day_window_usage, time_windows, max_daily,
            day=1, title=default_title, tags=["lifestyle"], duration_min=15, desc=default_desc
        )

    # 6. 生成摘要（修正语法错误）
    tw_desc = ", ".join([f"{w.label} ({w.start} - {w.end})" for w in time_windows])
    if lang == "zh":
        summary = (
            f"本计划为 {horizon} 天预览，类型：{', '.join(plan_types)}；"
            f"优先安排时段：{tw_desc}；每日最大时长：{max_daily} 分钟。"
            f"\n所有活动已分配具体时间段，无时间冲突；"
            f"所有建议均为一般性健康/训练建议，不替代线下专业诊疗。"
        )
    else:
        summary = (
            f"This is a {horizon}-day preview plan, type: {', '.join(plan_types)};"
            f" Priority time slots: {tw_desc}; Max daily duration: {max_daily} minutes."
            f"\nAll activities are assigned specific time slots with no conflicts;"
            f" All recommendations are general health/training advice and do not replace offline professional medical consultation."
        )

    # 7. 返回结果
    payload = {
        "plan_types": plan_types,
        "horizon_days": horizon,
        "time_windows": [{"label": w.label, "start": w.start, "end": w.end} for w in time_windows],
        "constraints": {"max_daily_minutes": max_daily},
        "modules": modules,
        "keywords": kw,
        "summary": summary,
        "language": lang,
        "memory": memory,
    }

    try:
        return PlanDraft(**payload)
    except Exception as e:
        print(f"PlanDraft init error: {e}")
        return payload


# # -------------------------- 测试（验证项目数量）--------------------------
# if __name__ == "__main__":
#     # 测试中文输入（还原原始多项目效果）
#     chinese_input = "生成7天健身计划"
#     chinese_config = {"plan_types": ["fitness", "lifestyle", "nutrition"]}
#     chinese_plan = draft_plan(chinese_input, chinese_config)
#     normalized = normalize_draft(chinese_plan)
#     print("=== 中文计划测试（项目数量）===")
#     print(f"总项目数：{len(normalized['modules'])}")  # 7天 × 3类型 × 2-3项目 ≈ 40-60个
#     # 统计每天项目数
#     day_count = {}
#     for mod in normalized['modules']:
#         day = mod['day']
#         day_count[day] = day_count.get(day, 0) + 1
#     for day, count in sorted(day_count.items()):
#         print(f"第{day}天项目数：{count} 个")  # 每天3-6个项目，符合原始预期
#
#     print("\n" + "=" * 50 + "\n")
#
#     # 测试英文输入（双语+多项目）
#     english_input = "7-day fitness and nutrition plan"
#     english_config = {"max_daily_minutes": 90}
#     english_plan = draft_plan(english_input, english_config)
#     eng_normalized = normalize_draft(english_plan)
#     print("=== English Plan Test (Number of Items) ===")
#     print(f"Total Modules: {len(eng_normalized['modules'])}")
#     day_count_en = {}
#     for mod in eng_normalized['modules']:
#         day = mod['day']
#         day_count_en[day] = day_count_en.get(day, 0) + 1
#     for day, count in sorted(day_count_en.items()):
#         print(f"Day {day}: {count} items")
# def normalize_draft(obj: Any) -> Dict[str, Any]:
#     """把各种返回类型归一化成 dict，方便主程序使用。"""
#     if obj is None:
#         return {}
#     if isinstance(obj, dict):
#         return obj
#
#     # pydantic
#     try:
#         from pydantic import BaseModel  # type: ignore
#     except Exception:
#         BaseModel = None  # type: ignore
#
#     if BaseModel is not None and isinstance(obj, BaseModel):
#         if hasattr(obj, "model_dump"):
#             return obj.model_dump()
#         return obj.dict()
#
#     # dataclass
#     if is_dataclass(obj):
#         return asdict(obj)
#
#     # 其他对象：尽力转 dict
#     if hasattr(obj, "__dict__"):
#         try:
#             return dict(obj.__dict__)
#         except Exception:
#             pass
#
#     try:
#         return dict(obj)
#     except Exception:
#         return {"_repr": repr(obj)}
