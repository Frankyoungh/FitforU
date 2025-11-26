# application/act.py
# Turn plan draft -> scheduled actions -> ICS / checklist

from __future__ import annotations
from datetime import datetime, date, timedelta
from typing import Dict, Any, List
import uuid

def _first_window(draft: Dict[str, Any]) -> Dict[str, str]:
    tws = draft.get("time_windows") or []
    if not isinstance(tws, list) or not tws:
        return {"label": "evening", "start": "20:00", "end": "21:00"}
    tw = tws[0] or {}
    s = str(tw.get("start", "20:00"))[:5]
    e = str(tw.get("end", "21:00"))[:5]
    return {"label": str(tw.get("label", "")), "start": s, "end": e}

def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    try:
        h, m = str(hhmm).split(":")[:2]
        return int(h), int(m)
    except Exception:
        return 20, 0

def _fmt_dt(dt: datetime) -> str:
    # ICS basic local time (no TZ); keep it simple for export
    return dt.strftime("%Y%m%dT%H%M%S")

def _tags_text(tags) -> str:
    if not tags:
        return ""
    if isinstance(tags, dict):
        return str(tags.get("id") or "")
    if isinstance(tags, (list, tuple)):
        parts = []
        for t in tags:
            if isinstance(t, dict):
                if t.get("id"):
                    parts.append(str(t["id"]))
            else:
                parts.append(str(t))
        return ", ".join(parts)
    return str(tags)

def build_actions(draft: Dict[str, Any], start_date: date) -> List[Dict[str, Any]]:
    """
    From a normalized draft (dict) produce dated actions:
    each action: {uid, summary, description, dtstart, dtend, tags, module}
    """
    win = _first_window(draft)
    sh, sm = _parse_hhmm(win["start"])
    eh, em = _parse_hhmm(win["end"])
    default_dur = (eh * 60 + em) - (sh * 60 + sm)
    if default_dur <= 0:
        default_dur = 45

    actions: List[Dict[str, Any]] = []
    modules = draft.get("modules") or []
    for i, m in enumerate(modules, 1):
        # day offset：若没给 day，就按顺序排
        day_offset = int(m.get("day", i)) - 1
        d = start_date + timedelta(days=max(0, day_offset))

        dur_min = int(m.get("duration_min") or m.get("duration") or default_dur)
        dtstart = datetime(d.year, d.month, d.day, sh, sm, 0)
        dtend = dtstart + timedelta(minutes=dur_min)

        title = m.get("title") or m.get("name") or f"Module {i}"
        tagtxt = _tags_text(m.get("tags") or m.get("labels"))
        if tagtxt:
            summary = f"{title} · {tagtxt}"
        else:
            summary = title

        desc = m.get("desc") or m.get("description") or ""

        actions.append({
            "uid": uuid.uuid4().hex,
            "summary": summary,
            "description": desc,
            "dtstart": dtstart,
            "dtend": dtend,
            "tags": tagtxt,
            "module": m,
        })
    return actions

def to_ics(actions: List[Dict[str, Any]], name: str = "FitForU Plan") -> str:
    now = _fmt_dt(datetime.utcnow())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "PRODID:-//FitForU//EN",
        f"X-WR-CALNAME:{name}",
    ]
    for a in actions:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{a['uid']}@fitforu",
            f"DTSTAMP:{now}Z",
            f"DTSTART:{_fmt_dt(a['dtstart'])}",
            f"DTEND:{_fmt_dt(a['dtend'])}",
            f"SUMMARY:{str(a['summary']).replace(',', '\\,').replace(';','\\;')}",

        ]
        if a.get("description"):
            desc = str(a["description"]).replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
            lines.append(f"DESCRIPTION:{desc}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)

def to_checklist_md(actions):
    lines = []
    for a in actions:
        dt = a.get("dtstart")
        if not dt:
            try:
                dt = datetime.strptime(f"{a['date']} {a.get('start','00:00')}", "%Y-%m-%d %H:%M")
            except Exception:
                dt = None
        when = dt.strftime("%m/%d %H:%M") if dt else f"{a.get('date','?')} {a.get('start','?')}"
        title = a.get("summary") or a.get("title") or "(未命名)"
        lines.append(f"- [ ] {when} · {title}")
    return "\n".join(lines)