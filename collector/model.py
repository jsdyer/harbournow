"""Validate AIS messages; preserve absent fields and conservative movement evidence."""
import math
import re
from datetime import datetime, timezone

POSITION_TYPES = {"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport", "LongRangeAisBroadcastMessage"}
STATIC_TYPES = {"ShipStaticData", "StaticDataReport"}


def number(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value if minimum <= value <= maximum else None


def clean(value, limit=80):
    if not isinstance(value, str):
        return None
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", "", value).replace("@", " ").split())[:limit] or None


def parse_time(value, now):
    if not isinstance(value, str):
        return now
    try:
        # AISStream uses ISO timestamps, sometimes followed by '+0000 UTC'.
        stamp = value.replace(" UTC", "").replace(" +0000", "+00:00").replace("Z", "+00:00")
        dt = datetime.fromisoformat(stamp)
        if dt.tzinfo is None:
            return now
        result = dt.timestamp()
        return result if now - 86400 <= result <= now + 30 else None
    except (ValueError, OverflowError):
        return None


def normalize(envelope, now):
    if not isinstance(envelope, dict):
        return None
    kind = envelope.get("MessageType")
    if kind not in POSITION_TYPES | STATIC_TYPES:
        return None
    meta = envelope.get("MetaData")
    msg = envelope.get("Message")
    if not isinstance(meta, dict) or not isinstance(msg, dict):
        return None
    body = msg.get(kind)
    if not isinstance(body, dict) or body.get("Valid") is False:
        return None
    mmsi = str(meta.get("MMSI", body.get("UserID", "")))
    if not re.fullmatch(r"[1-9][0-9]{8}", mmsi):
        return None
    observed = parse_time(meta.get("time_utc"), now)
    if observed is None:
        return None
    item = {"mmsi": mmsi, "observed_at": observed}
    name = clean(body.get("Name") or meta.get("ShipName"))
    if name:
        item["name"] = name
    if kind in POSITION_TYPES:
        lat = number(body.get("Latitude", meta.get("latitude", meta.get("Latitude"))), -90, 90)
        lon = number(body.get("Longitude", meta.get("longitude", meta.get("Longitude"))), -180, 180)
        if lat is None or lon is None:
            return None
        item.update(lat=lat, lon=lon, position_at=observed)
        for dest, source, high in [("speed", "Sog", 102.2), ("course", "Cog", 359.9), ("heading", "TrueHeading", 359), ("nav_status", "NavigationalStatus", 14)]:
            item[dest] = number(body.get(source), 0, high)
        if kind == "ExtendedClassBPositionReport":
            item["ship_type"] = number(body.get("Type"), 0, 99)
    else:
        # Class B static data is split into reports A and B.
        a = body.get("ReportA") if isinstance(body.get("ReportA"), dict) else {}
        b = body.get("ReportB") if isinstance(body.get("ReportB"), dict) else {}
        for key, value in {"name": clean(body.get("Name") or a.get("Name") or meta.get("ShipName")), "callsign": clean(body.get("CallSign") or b.get("CallSign"), 20), "destination": clean(body.get("Destination")), "ship_type": number(body.get("Type", b.get("ShipType")), 0, 99), "imo": number(body.get("ImoNumber"), 1000000, 9999999)}.items():
            if value is not None:
                item[key] = value
        item["static_at"] = observed
    return item


def inside(lat, lon, polygon):
    result = False
    previous = polygon[-1]
    for current in polygon:
        y1, x1 = previous
        y2, x2 = current
        if (y1 > lat) != (y2 > lat) and lon < (x2-x1)*(lat-y1)/(y2-y1)+x1:
            result = not result
        previous = current
    return result


def in_bbox(lat, lon, bbox):
    a, b = bbox
    return min(a[0], b[0]) <= lat <= max(a[0], b[0]) and min(a[1], b[1]) <= lon <= max(a[1], b[1])


def classify(ship, harbour):
    within = inside(ship["lat"], ship["lon"], harbour["boundary"])
    # Slow speed alone is insufficient: require the configured anchorage zone.
    anchor = within and inside(ship["lat"], ship["lon"], harbour["anchorage"]) and (ship.get("nav_status") == 1 or (ship.get("speed") is not None and ship["speed"] <= 0.5))
    return within, bool(anchor)


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z") if timestamp is not None else None
