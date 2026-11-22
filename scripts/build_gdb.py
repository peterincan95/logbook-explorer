"""Build a file geodatabase for ArcGIS Pro with the logbook points and geocoded places.

Run with ArcGIS Pro's Python (needs arcpy):

    "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" scripts/build_gdb.py

Writes gis/cliwoc_explorer.gdb (replaced on every run) containing:

- locations: one point per location (location_id is the key), from
  data/locations.csv, which build_locations.py rebuilds first. Spelling
  variants and other names that resolved to the same point are merged; the
  names as written are listed in names_as_written. Locations without
  coordinates (at sea, not a place, not found) keep an empty geometry so
  every ID still joins.
- logbook_points: every logbook row from data/cliwoc_points_en.csv (original
  fields plus the _en translations), with origin_location_id,
  destination_location_id and anchor_location_id pointing at
  locations.location_id, obs_date built from YR, MO, DY and HR, and the
  track fields from build_tracks.py: track_id (one ship's voyage),
  track_seq (order along it) and track_duplicate (0 = keep; 1+ = likely
  copy of the same voyage from another source). Rows without a position
  have an empty geometry. To draw voyages as lines: Points To Line with
  Line Field = track_id, Sort Field = track_seq.
- tracks: one row per track_id (ship, dates, route, row counts).
- voyage_lines: one line per track, joining its positioned points in
  track_seq order, with nationality, ship, company, origin and destination
  location IDs and the track fields. Tracks are split where they cross the
  180th meridian so no segment runs across the whole map (see
  track_lines.py); such tracks are multipart lines.
- Relationship classes linking each location to the logbook rows that start
  at, end at, or anchor at it, and each track to its logbook rows.
"""
import argparse
import datetime as dt
import html
import math
import re
import sys
from pathlib import Path

import arcpy
import pandas as pd

import build_locations
import build_tracks
from track_lines import MAX_SEGMENT_KM, track_lines

ROOT = Path(__file__).resolve().parent.parent
LOG_CSV = ROOT / "data" / "cliwoc_points_en.csv"
SCHEMA_INI = ROOT / "data" / "schema.ini"
DICTIONARY = ROOT / "docs" / "cliwoc21_data_dictionary_full.htm"
GDB = ROOT / "gis" / "cliwoc_explorer.gdb"
WGS84 = arcpy.SpatialReference(4326)
CHUNK = 20000

PLACE_LINKS = [("VoyageFrom", "origin_location_id", "Origin location ID"),
               ("VoyageTo", "destination_location_id", "Destination location ID"),
               ("AnchorPlace", "anchor_location_id", "Anchor location ID")]

LOCATION_ALIASES = {
    "location_id": "Location ID", "common_name": "Most common name as written",
    "modern_name": "Modern name", "place_type": "Place type", "country_code": "Country code",
    "lat": "Latitude", "lon": "Longitude", "precision": "Location precision",
    "confidence": "Geocoding confidence", "source": "Coordinate source", "flag_reason": "Review flag",
    "note": "Note", "voyages": "Voyages", "rows_from": "Logbook rows (origin)",
    "rows_to": "Logbook rows (destination)", "rows_anchor": "Logbook rows (anchored)",
    "first_year": "First year", "last_year": "Last year", "languages": "Logbook languages",
    "nationalities": "Ship nationalities", "name_count": "Number of names as written",
    "names_as_written": "Names as written",
}
LOCATION_NUMERIC = {"location_id": "LONG", "voyages": "LONG", "rows_from": "LONG", "rows_to": "LONG",
                    "rows_anchor": "LONG", "first_year": "LONG", "last_year": "LONG", "name_count": "LONG",
                    "lat": "DOUBLE", "lon": "DOUBLE"}

TRACK_FIELDS = [("track_id", ("TEXT", 20), "Track ID (ship's voyage)"),
                ("track_seq", ("LONG", None), "Order along track"),
                ("track_duplicate", ("SHORT", None), "Likely duplicate track (0 = keep)")]
TRACK_TABLE_ALIASES = {
    "track_id": "Track ID", "ID": "Ship/logbook ID", "ship": "Ship name",
    "voyage_ini": "Voyage start (VoyageIni)", "start_inferred": "Start date inferred (1 = yes)",
    "first_date": "First observation", "last_date": "Last observation",
    "voyage_from": "Origin as written", "voyage_to": "Destination as written",
    "rows": "Logbook rows", "positioned": "Rows with a position",
    "track_duplicate": "Likely duplicate track (0 = keep)",
}


def clean_place(s):
    """Same normalisation build_place_table.py used when it listed the places."""
    return s.str.strip().str.replace(r"\s+", " ", regex=True)


# Fields the dictionary doesn't describe, or whose description doesn't start with a name.
ALIAS_OVERRIDES = {
    "latitude": "Latitude (decimal degrees)",
    "longitude": "Longitude (decimal degrees)",
    "Decl": "Magnetic declination",
}


def dictionary_aliases():
    """Field aliases from the CLIWOC data dictionary: the first clause of each
    description (the full text stays in docs/), e.g. W -> "Wind speed, given in
    tenths of a meter per second". Unused fields become "Not in use (DS)"."""
    page = DICTIONARY.read_text(encoding="utf-8", errors="replace")
    text = lambda c: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
    aliases = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) < 5 or cells[0] in aliases or not cells[4]:
            continue
        name, desc = cells[0], cells[4]
        if desc == "Not in use":
            aliases[name] = f"Not in use ({name})"
            continue
        parts = [x.strip() for x in re.split(r";|: |\. ", desc)]
        alias = parts[0]
        if len(parts) > 1 and parts[1].lower().startswith("given in"):
            alias += ", " + parts[1]
        # Drop a "from" left dangling by the cut ("...in whole degrees from: 1-360")
        alias = re.sub(r",?\s+originating\s+from$|(?<=degrees) from$", "", alias.rstrip(".,"))
        aliases[name] = alias[:255]
    aliases.update(ALIAS_OVERRIDES)
    return aliases


def logbook_alias(field, aliases):
    if field.endswith("_en") and field[:-3] in aliases:
        return f"{aliases[field[:-3]]} (English)"[:255]
    return aliases.get(field, field)


def schema_types():
    types = {}
    for line in SCHEMA_INI.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"Col\d+=(\S+)\s+(\w+)", line.strip())
        if m:
            types[m.group(1)] = m.group(2).lower()
    return types


def field_spec(name, series, declared):
    """Pick an arcpy field type, checking the declared type against the values."""
    vals = series[series.str.strip() != ""].str.strip()
    if declared in ("long", "double") and len(vals):
        nums = pd.to_numeric(vals, errors="coerce")
        if nums.notna().all():
            if declared == "long" and (nums % 1 == 0).all() and nums.abs().max() < 2**31:
                return ("LONG", None)
            return ("DOUBLE", None)
    length = int(series.str.len().max() or 1)
    return ("TEXT", max(length, 1))


def convert(v, ftype):
    if v is None or v == "" or (isinstance(v, float) and math.isnan(v)):
        return None
    if ftype == "LONG":
        return int(float(v))
    if ftype == "DOUBLE":
        return float(v)
    return str(v)


def obs_date(yr, mo, dy, hr):
    try:
        d = dt.datetime(int(yr), int(mo), int(dy))
    except (TypeError, ValueError):
        return None
    try:
        h = float(hr) / 100        # HR is hours x 100 (1330 = 13:30)
        if 0 <= h < 24:
            d += dt.timedelta(hours=h)
    except (TypeError, ValueError):
        pass
    return d


def point(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if math.isnan(lat) or math.isnan(lon):
        return None
    return (lon, lat)


def create_fc(name, fields, alias, geometry="POINT"):
    fc = str(GDB / name)
    arcpy.management.CreateFeatureclass(str(GDB), name, geometry, spatial_reference=WGS84, out_alias=alias)
    for fname, (ftype, length), falias in fields:
        arcpy.management.AddField(fc, fname, ftype, field_length=length, field_alias=falias)
    return fc


# ------------------------------------------------------------------ locations

def build_location_fc():
    locs, crosswalk = build_locations.build()
    df = locs.astype(str).replace({"<NA>": "", "nan": ""})
    order = list(df.columns)
    fields = []
    for c in order:
        spec = (LOCATION_NUMERIC[c], None) if c in LOCATION_NUMERIC else             ("TEXT", max(int(df[c].str.len().max() or 1), 1))
        fields.append((c, spec, LOCATION_ALIASES.get(c, c)))
    fc = create_fc("locations", fields, "Voyage locations (geocoded)")
    types = {f[0]: f[1][0] for f in fields}
    with arcpy.da.InsertCursor(fc, ["SHAPE@XY"] + order) as cur:
        for rec in df.to_dict("records"):
            cur.insertRow([point(rec["lat"], rec["lon"])] + [convert(rec[c], types[c]) for c in order])
    arcpy.management.AddIndex(fc, "location_id", "idx_location_id", "UNIQUE")
    print(f"locations: {len(df):,} locations, {(df.lat != '').sum():,} with coordinates")
    return dict(zip(crosswalk.place, crosswalk.location_id.astype(int)))


# ------------------------------------------------------------------- logbook

def build_logbook(location_ids):
    declared = schema_types()
    aliases = dictionary_aliases()
    print("Scanning logbook fields...")
    full = pd.read_csv(LOG_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    cols = list(full.columns)
    fields = []
    for c in cols:
        spec = field_spec(c, full[c], declared.get(c, "text"))
        fields.append((c, spec, logbook_alias(c, aliases)))
    link_fields = [(new, ("LONG", None), alias) for _, new, alias in PLACE_LINKS]
    fields += link_fields + [("obs_date", ("DATE", None), "Observation date (YR, MO, DY, HR)")] + TRACK_FIELDS
    fc = create_fc("logbook_points", fields, "CLIWOC logbook points")
    types = {f[0]: f[1][0] for f in fields}

    for src, new, _ in PLACE_LINKS:
        full[new] = clean_place(full[src]).map(location_ids)
    unmatched = {src: int(((clean_place(full[src]) != "") & full[new].isna()).sum()) for src, new, _ in PLACE_LINKS}
    print("Unmatched place names:", unmatched)
    if any(unmatched.values()):
        raise SystemExit("Some logbook place names have no location; re-run the place steps")

    track_rows, tracks = build_tracks.assign_tracks(full)
    for c in track_rows.columns:
        full[c] = track_rows[c]

    out_cols = cols + [new for _, new, _ in PLACE_LINKS]
    track_cols = [f[0] for f in TRACK_FIELDS]
    idx = {c: i for i, c in enumerate(out_cols)}
    n = 0
    with arcpy.da.InsertCursor(fc, ["SHAPE@XY"] + out_cols + ["obs_date"] + track_cols) as cur:
        for start in range(0, len(full), CHUNK):
            part = full.iloc[start:start + CHUNK]
            for row, trk in zip(part[out_cols].itertuples(index=False, name=None),
                                part[track_cols].itertuples(index=False, name=None)):
                vals = [convert(v, types[c]) for c, v in zip(out_cols, row)]
                d = obs_date(row[idx["YR"]], row[idx["MO"]], row[idx["DY"]], row[idx["HR"]])
                cur.insertRow([point(row[idx["latitude"]], row[idx["longitude"]])] + vals + [d]
                              + [trk[0], int(trk[1]), int(trk[2])])
            n += len(part)
            print(f"  {n:,}/{len(full):,}", flush=True)
    for _, new, _ in PLACE_LINKS:
        arcpy.management.AddIndex(fc, new, f"idx_{new}")
    arcpy.management.AddIndex(fc, "track_id", "idx_track_id")
    build_track_table(tracks)
    build_line_fc(full, tracks)
    with_pos = int(((full.latitude.str.strip() != "") & (full.longitude.str.strip() != "")).sum())
    print(f"logbook_points: {len(full):,} rows, {with_pos:,} with positions, {len(fields)} fields")


def build_track_table(tracks):
    table = str(GDB / "tracks")
    arcpy.management.CreateTable(str(GDB), "tracks", out_alias="Logbook tracks (one per voyage)")
    numeric = {"rows": "LONG", "positioned": "LONG", "track_duplicate": "SHORT", "start_inferred": "SHORT"}
    df = tracks.copy()
    df["start_inferred"] = df.start_inferred.astype(int)
    df = df.astype(object).where(df.notna(), None)
    for c in df.columns:
        ftype = numeric.get(c, "TEXT")
        length = max(int(df[c].astype(str).str.len().max()), 1) if ftype == "TEXT" else None
        arcpy.management.AddField(table, c, ftype, field_length=length, field_alias=TRACK_TABLE_ALIASES[c])
    with arcpy.da.InsertCursor(table, list(df.columns)) as cur:
        for rec in df.itertuples(index=False, name=None):
            cur.insertRow([None if v is None else (int(v) if c in numeric else str(v))
                           for c, v in zip(df.columns, rec)])
    arcpy.management.AddIndex(table, "track_id", "idx_track_id", "UNIQUE")
    print(f"tracks: {len(df):,} tracks, {(df.track_duplicate > 0).sum():,} likely duplicates")


# Attributes of each voyage line: (field, alias, type, length) and how it is
# taken from the track's points (see track_lines.track_lines).
LINE_FIELDS = [
    ("track_id", "Track ID (ship's voyage)", "TEXT", 20, ("track_id", "first")),
    ("ship", "Ship name", "TEXT", 100, ("ShipName", "mode")),
    ("nationality", "Nationality", "TEXT", 30, ("Nationality", "mode")),
    ("company", "Company", "TEXT", 30, ("Company", "mode")),
    ("origin_location_id", "Origin location ID", "LONG", None, ("origin_location_id", "mode")),
    ("destination_location_id", "Destination location ID", "LONG", None, ("destination_location_id", "mode")),
    ("voyage_from", "Origin as written", "TEXT", 255, ("VoyageFrom", "mode")),
    ("voyage_to", "Destination as written", "TEXT", 255, ("VoyageTo", "mode")),
    ("first_date", "First observation", "DATE", None, ("date", "min")),
    ("last_date", "Last observation", "DATE", None, ("date", "max")),
    ("points", "Positioned points", "LONG", None, ("track_seq", "count")),
    ("track_duplicate", "Likely duplicate track (0 = keep)", "SHORT", None, ("track_duplicate", "first")),
]


def build_line_fc(full, tracks):
    """One polyline per track through its positioned points, split at the
    180th meridian. Values that vary along a track (e.g. a company or
    destination that changes mid-voyage) take the most common one."""
    df = full.copy()
    df["lat"] = pd.to_numeric(df.latitude, errors="coerce")
    df["lon"] = pd.to_numeric(df.longitude, errors="coerce")
    df = df[df.lat.notna() & df.lon.notna()]
    df["date"] = pd.to_datetime(dict(year=pd.to_numeric(df.YR, errors="coerce"),
                                     month=pd.to_numeric(df.MO, errors="coerce"),
                                     day=pd.to_numeric(df.DY, errors="coerce")), errors="coerce")
    for c in ("origin_location_id", "destination_location_id"):
        df[c] = df[c].astype("Int64").astype(str).replace("<NA>", "")
    fields = [(name, (ftype, length), alias) for name, alias, ftype, length, _ in LINE_FIELDS]
    fc = create_fc("voyage_lines", fields, "Voyage lines (one per track)", geometry="POLYLINE")
    names = [f[0] for f in LINE_FIELDS]
    attrs = {f[0]: f[4] for f in LINE_FIELDS}
    n = split = crossed = 0
    with arcpy.da.InsertCursor(fc, ["SHAPE@"] + names) as cur:
        for tid, parts, v in track_lines(df, attrs):
            geom = arcpy.Polyline(arcpy.Array([arcpy.Array([arcpy.Point(x, y) for x, y in p]) for p in parts]),
                                  WGS84)
            row = []
            for name, alias, ftype, length, _ in LINE_FIELDS:
                x = v[name]
                if x in ("", None):
                    row.append(None)
                elif ftype in ("LONG", "SHORT"):
                    row.append(int(float(x)))
                elif ftype == "DATE":
                    row.append(x.to_pydatetime())
                else:
                    row.append(str(x)[:length])
            cur.insertRow([geom] + row)
            n += 1
            split += len(parts) > 1
            crossed += any(abs(x) == 180 for part in parts for x, _ in part)
    arcpy.management.AddIndex(fc, "track_id", "idx_track_id", "UNIQUE")
    print(f"voyage_lines: {n:,} lines ({len(tracks) - n:,} tracks have under two distinct positions), "
          f"{split:,} multipart: split at gaps over {MAX_SEGMENT_KM:,} km or where they cross the 180th meridian "
          f"({crossed:,} cross it)")


def track_line_relationship():
    arcpy.management.CreateRelationshipClass(
        str(GDB / "tracks"), str(GDB / "voyage_lines"), str(GDB / "rel_track_line"), "SIMPLE",
        "Voyage line", "Track", "NONE", "ONE_TO_ONE", "NONE", "track_id", "track_id")


def rebuild_lines():
    """Replace only voyage_lines in the existing geodatabase (works while Pro
    has the geodatabase open, as long as voyage_lines itself isn't in a map)."""
    arcpy.env.overwriteOutput = True
    full = pd.read_csv(LOG_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False,
                       usecols=list(dict.fromkeys(build_tracks.COLS + ["Nationality", "Company", "AnchorPlace"])))
    xw = pd.read_csv(ROOT / "data" / "place_to_location.csv", encoding="utf-8-sig", keep_default_na=False)
    ids = dict(zip(xw.place, xw.location_id.astype(int)))
    for src, new, _ in PLACE_LINKS:
        full[new] = clean_place(full[src]).map(ids)
    track_rows, tracks = build_tracks.assign_tracks(full)
    full = full.join(track_rows)
    for name in ("rel_track_line", "voyage_lines"):
        if arcpy.Exists(str(GDB / name)):
            arcpy.management.Delete(str(GDB / name))
    build_line_fc(full, tracks)
    track_line_relationship()


def build_relationships():
    locs, logs = str(GDB / "locations"), str(GDB / "logbook_points")
    for _, key, alias in PLACE_LINKS:
        label = alias.replace(" location ID", "").lower()   # origin / destination / anchor
        arcpy.management.CreateRelationshipClass(
            locs, logs, str(GDB / f"rel_location_{label}"), "SIMPLE",
            f"Logbook points ({label})", f"{label.capitalize()} location", "NONE", "ONE_TO_MANY",
            "NONE", "location_id", key)
    arcpy.management.CreateRelationshipClass(
        str(GDB / "tracks"), logs, str(GDB / "rel_track_points"), "SIMPLE",
        "Logbook points", "Track", "NONE", "ONE_TO_MANY", "NONE", "track_id", "track_id")
    track_line_relationship()
    print("Relationship classes: origin, destination, anchor, track points, track line")


def apply_aliases():
    """Set dictionary aliases on an existing logbook_points without rebuilding it."""
    fc = str(GDB / "logbook_points")
    aliases = dictionary_aliases()
    n = 0
    for f in arcpy.ListFields(fc):
        if f.type in ("OID", "Geometry"):
            continue
        alias = logbook_alias(f.name, aliases)
        if alias != f.name and f.aliasName != alias:
            arcpy.management.AlterField(fc, f.name, new_field_alias=alias)
            n += 1
    print(f"Updated {n} aliases on logbook_points")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aliases-only", action="store_true",
                    help="only refresh field aliases on the existing geodatabase")
    ap.add_argument("--lines-only", action="store_true",
                    help="only rebuild voyage_lines in the existing geodatabase")
    args = ap.parse_args()
    if args.aliases_only:
        apply_aliases()
        return
    if args.lines_only:
        rebuild_lines()
        return
    arcpy.env.overwriteOutput = True
    GDB.parent.mkdir(exist_ok=True)
    if arcpy.Exists(str(GDB)):
        arcpy.management.Delete(str(GDB))
    arcpy.management.CreateFileGDB(str(GDB.parent), GDB.name)
    location_ids = build_location_fc()
    build_logbook(location_ids)
    build_relationships()
    print(f"Done: {GDB}")


if __name__ == "__main__":
    main()
