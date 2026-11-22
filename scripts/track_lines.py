"""Turn track points into line geometry that never jumps across the map.

Used by build_gdb.py (voyage_lines feature class) and build_web_data.py
(lines.geojson). Points are joined in track_seq order in plain longitude /
latitude. Where two consecutive points are more than 180 degrees of longitude
apart, the ship took the short way across the 180th meridian, not the long way
round the world. Joining them directly would draw a line across the whole map,
so the track is split there instead: the line runs to longitude 180 (or -180)
at the latitude where it crosses, and a new part starts on the other side. The
result is a multipart line.

Tracks are also broken wherever two consecutive points are more than
MAX_SEGMENT_KM apart (great-circle distance). A day's sailing is rarely over
450 km (99% of one-day steps), so longer steps are gaps in the record (days or
weeks with no position) or mistyped positions, and a straight line across
them would cut across land. Nothing is drawn across such a gap; a point
stranded between two gaps stays a point and isn't part of the line.
"""
import math
from collections import Counter

import pandas as pd

MAX_SEGMENT_KM = 1000


def distance_km(lon1, lat1, lon2, lat2):
    """Great-circle distance (the short way, including across the 180th meridian)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def split_line(coords, max_km=MAX_SEGMENT_KM):
    """coords: list of (lon, lat) in order. Returns a list of parts (each a list
    of (lon, lat) with at least two different vertices), broken at gaps over
    max_km and at the 180th meridian."""
    parts, part = [], []
    prev = None
    for lon, lat in coords:
        if prev is not None:
            plon, plat = prev
            if max_km and distance_km(plon, plat, lon, lat) > max_km:
                parts.append(part)
                part = []
            elif abs(lon - plon) > 180:
                # Crossing: unwrap the next point, find the latitude at the meridian
                edge = 180.0 if plon > 0 else -180.0
                ulon = lon + 360 if plon > 0 else lon - 360
                t = (edge - plon) / (ulon - plon)
                ylat = plat + t * (lat - plat)
                part.append((edge, ylat))
                parts.append(part)
                part = [(-edge, ylat)]
        if not part or part[-1] != (lon, lat):
            part.append((lon, lat))
        prev = (lon, lat)
    parts.append(part)
    return [p for p in parts if len(set(p)) >= 2]


def _mode(values):
    """Most common non-blank value (ties: the first seen)."""
    counts = Counter(v for v in values if v)
    return counts.most_common(1)[0][0] if counts else ""


def track_lines(df, attrs):
    """df: one row per point with track_id, track_seq, lon, lat (numeric) and
    the attribute columns. attrs: {output name: (column, how)} where how is
    "mode" (most common non-blank value), "first", "min", "max" or "count".
    Yields (track_id, parts, {name: value}) for every track that makes a line,
    in track_id order."""
    df = df.sort_values(["track_id", "track_seq"])
    for tid, g in df.groupby("track_id", sort=True):
        parts = split_line(list(zip(g.lon, g.lat)))
        if not parts:
            continue
        values = {}
        for name, (col, how) in attrs.items():
            s = g[col]
            if how == "mode":
                values[name] = _mode(str(x).strip() for x in s.tolist() if x is not None and not (isinstance(x, float) and math.isnan(x)))
            elif how == "count":
                values[name] = len(g)
            else:
                s = s.dropna()
                v = s.iat[0] if how == "first" and len(s) else getattr(s, how)() if len(s) else None
                values[name] = None if v is None or pd.isna(v) else v
        yield tid, parts, values
