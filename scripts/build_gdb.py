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
  locations.location_id, and obs_date built from YR, MO, DY and HR. Rows
  without a position have an empty geometry.
- Relationship classes linking each location to the logbook rows that start
  at, end at, or anchor at it.
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


def create_fc(name, fields, alias):
    fc = str(GDB / name)
    arcpy.management.CreateFeatureclass(str(GDB), name, "POINT", spatial_reference=WGS84, out_alias=alias)
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
    fields += link_fields + [("obs_date", ("DATE", None), "Observation date (YR, MO, DY, HR)")]
    fc = create_fc("logbook_points", fields, "CLIWOC logbook points")
    types = {f[0]: f[1][0] for f in fields}

    for src, new, _ in PLACE_LINKS:
        full[new] = clean_place(full[src]).map(location_ids)
    unmatched = {src: int(((clean_place(full[src]) != "") & full[new].isna()).sum()) for src, new, _ in PLACE_LINKS}
    print("Unmatched place names:", unmatched)
    if any(unmatched.values()):
        raise SystemExit("Some logbook place names have no location; re-run the place steps")

    out_cols = cols + [new for _, new, _ in PLACE_LINKS]
    idx = {c: i for i, c in enumerate(out_cols)}
    n = 0
    with arcpy.da.InsertCursor(fc, ["SHAPE@XY"] + out_cols + ["obs_date"]) as cur:
        for start in range(0, len(full), CHUNK):
            part = full.iloc[start:start + CHUNK][out_cols]
            for row in part.itertuples(index=False, name=None):
                vals = [convert(v, types[c]) for c, v in zip(out_cols, row)]
                d = obs_date(row[idx["YR"]], row[idx["MO"]], row[idx["DY"]], row[idx["HR"]])
                cur.insertRow([point(row[idx["latitude"]], row[idx["longitude"]])] + vals + [d])
            n += len(part)
            print(f"  {n:,}/{len(full):,}", flush=True)
    for _, new, _ in PLACE_LINKS:
        arcpy.management.AddIndex(fc, new, f"idx_{new}")
    with_pos = int(((full.latitude.str.strip() != "") & (full.longitude.str.strip() != "")).sum())
    print(f"logbook_points: {len(full):,} rows, {with_pos:,} with positions, {len(fields)} fields")


def build_relationships():
    locs, logs = str(GDB / "locations"), str(GDB / "logbook_points")
    for _, key, alias in PLACE_LINKS:
        label = alias.replace(" location ID", "").lower()   # origin / destination / anchor
        arcpy.management.CreateRelationshipClass(
            locs, logs, str(GDB / f"rel_location_{label}"), "SIMPLE",
            f"Logbook points ({label})", f"{label.capitalize()} location", "NONE", "ONE_TO_MANY",
            "NONE", "location_id", key)
    print("Relationship classes: origin, destination, anchor")


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
    if ap.parse_args().aliases_only:
        apply_aliases()
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
