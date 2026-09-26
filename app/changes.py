"""Signed changes between two actual responses, separate from the trend scorer."""


def changes(snapshots, fields):
    rows = sorted(snapshots, key=lambda r: r["observed_at"], reverse=True)
    current = rows[0] if rows else None
    previous = (
        next((r for r in rows[1:] if r["observed_at"] < current["observed_at"]), None)
        if current
        else None
    )
    seconds = current["observed_at"] - previous["observed_at"] if previous else None
    result = {
        "from_at": previous["observed_at"] if previous else None,
        "to_at": current["observed_at"] if current else None,
        "interval_hours": seconds / 3600 if seconds else None,
        "short_interval": seconds is not None and seconds < 300,
        "metrics": {},
    }
    for field in fields:
        value = current[field] if current else None
        before = previous[field] if previous else None
        delta = value - before if value is not None and before is not None else None
        result["metrics"][field] = {
            "value": value,
            "previous": before,
            "delta": delta,
            "percent": delta / before * 100 if delta is not None and before else None,
            "per_hour": delta * 3600 / seconds
            if delta is not None and seconds and seconds >= 1
            else None,
        }
    return result
