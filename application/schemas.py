# application/schemas.py
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import time

@dataclass
class TimeWindow:
    """可用时间窗（例如：晚间 19:00-22:00）"""
    label: str
    start: str  # "19:00"
    end: str    # "22:00"

@dataclass
class PlanDraft:
    """计划预览的单一事实源（仅预览，不落地、不出 .ics）"""
    plan_types: List[str] = field(default_factory=list)        # ["lifestyle","fitness",...]
    horizon_days: int = 7                                      # 3/7/14/30
    time_windows: List[TimeWindow] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)  # 饮食/过敏/时间窗/伤病回避...
    modules: List[Dict[str, Any]] = field(default_factory=list) # 预选模块（不含日程）
    keywords: List[str] = field(default_factory=list)          # 从用户输入抽取的词
    summary: str = ""                                          # 面向人类的简要说明

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # dataclass 的 TimeWindow -> dict 已经由 asdict 处理
        return d

# ----------- 一些可复用的小工具 -----------

def window(label: str, start: str, end: str) -> TimeWindow:
    return TimeWindow(label=label, start=start, end=end)

DEFAULT_WINDOWS = [
    window("evening", "19:00", "22:00")
]
