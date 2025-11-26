# ========== application/profile.py ==========
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class TimeWindow:
    label: str
    start: str  # 'HH:MM'
    end: str    # 'HH:MM'
    days: List[int] = field(default_factory=lambda: [1,2,3,4,5,6,7])

    def as_dict(self) -> Dict[str, Any]:
        return {"label": self.label, "start": self.start, "end": self.end, "days": self.days}

@dataclass
class Profile:
    tz: str = "Asia/Shanghai"
    time_windows: List[TimeWindow] = field(default_factory=lambda: [TimeWindow("evening", "19:00", "22:00")])
    max_daily_minutes: int = 120
    # 最小间隔（小时）——在 composer 中会转为按天检查
    min_muscle_gap_h: Dict[str, int] = field(default_factory=lambda: {
        "upper_push": 48, "upper_pull": 48, "legs": 72, "core": 24
    })
    unavailable_dates: List[str] = field(default_factory=list)  # 'YYYY-MM-DD'
    avoid: Dict[str, Any] = field(default_factory=lambda: {
        "high_impact_cooldown_days": 0,
        "muscle_groups": []  # e.g. ["legs"]
    })

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tz": self.tz,
            "time_windows": [tw.as_dict() for tw in self.time_windows],
            "max_daily_minutes": self.max_daily_minutes,
            "min_muscle_gap_h": self.min_muscle_gap_h,
            "unavailable_dates": self.unavailable_dates,
            "avoid": self.avoid,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Profile":
        if not d:
            return Profile()
        tws: List[TimeWindow] = []
        for tw in d.get("time_windows", []):
            lab = (tw.get("label") or "evening").strip()
            st = (tw.get("start") or "19:00")[:5]
            ed = (tw.get("end") or "22:00")[:5]
            days = [int(x) for x in (tw.get("days") or [1,2,3,4,5,6,7])]
            tws.append(TimeWindow(lab, st, ed, days))
        return Profile(
            tz=d.get("tz", "Asia/Shanghai"),
            time_windows=tws or [TimeWindow("evening", "19:00", "22:00")],
            max_daily_minutes=int(d.get("max_daily_minutes", 120)),
            min_muscle_gap_h=dict(d.get("min_muscle_gap_h", {"upper_push":48, "upper_pull":48, "legs":72, "core":24})),
            unavailable_dates=list(d.get("unavailable_dates", [])),
            avoid=dict(d.get("avoid", {"high_impact_cooldown_days": 0, "muscle_groups": []}))
        )
