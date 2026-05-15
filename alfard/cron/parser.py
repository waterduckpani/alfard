"""Human-friendly schedule parser — converts natural language and
cron expressions into APScheduler trigger kwargs."""

import re

def parse_schedule(schedule_str: str) -> dict:
    s = schedule_str.strip().lower()

    named = {"midnight": (0,0), "noon": (12,0), "morning": (8,0), "evening": (18,0)}
    if s in named:
        h, m = named[s]
        return {"trigger": "cron", "kwargs": {"hour": h, "minute": m}}

    if s in ("daily", "every day"):
        return {"trigger": "interval", "kwargs": {"days": 1}}
    if s in ("weekly", "every week"):
        return {"trigger": "interval", "kwargs": {"weeks": 1}}
    if s in ("hourly", "every hour"):
        return {"trigger": "interval", "kwargs": {"hours": 1}}

    m = re.match(r"every\s+(\d+)\s*h(?:ours?)?$", s)
    if m: return {"trigger": "interval", "kwargs": {"hours": int(m.group(1))}}

    m = re.match(r"every\s+(\d+)\s*m(?:in(?:utes?)?)?$", s)
    if m: return {"trigger": "interval", "kwargs": {"minutes": int(m.group(1))}}

    m = re.match(r"every\s+(\d+)\s*d(?:ays?)?$", s)
    if m: return {"trigger": "interval", "kwargs": {"days": int(m.group(1))}}

    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", s)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        meridiem = m.group(3)
        if meridiem == "pm" and hour != 12: hour += 12
        elif meridiem == "am" and hour == 12: hour = 0
        return {"trigger": "cron", "kwargs": {"hour": hour, "minute": minute}}

    parts = schedule_str.strip().split()
    if len(parts) == 5:
        minute, hour, day, month, dow = parts
        return {"trigger": "cron", "kwargs": {
            "minute": minute, "hour": hour, "day": day,
            "month": month, "day_of_week": dow,
        }}

    raise ValueError(
        f"Unrecognised schedule: {schedule_str!r}\n"
        "Examples: '8am', 'every 1h', 'daily', '0 8 * * *'"
    )
