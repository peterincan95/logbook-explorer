"""Build a table of every unique place named in VoyageFrom, VoyageTo and AnchorPlace.

Writes data/voyage_places.csv with one row per place as written in the data
(the join key back to the logbook rows), plus:

- group_key: accent-, case- and punctuation-folded name, so spelling variants
  such as CADIZ / CÁDIZ can be geocoded together
- usage counts, languages, nationalities, years and example ships
- position hints from the ship tracks: the median first logged position of
  voyages leaving from the place and the median last position of voyages
  arriving at it. Logs often start or end at sea, so these are a rough
  sanity check for geocoding, not a location. The anchor hint (median
  position logged while anchored at the place) is usually much closer.

    python scripts/build_place_table.py
"""
import math
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV_IN = ROOT / "data" / "cliwoc_points.csv"
CSV_OUT = ROOT / "data" / "voyage_places.csv"

COLS = ["InstAbbr", "LogbookIdent", "LogbookLanguage", "Nationality", "ShipName",
        "YR", "MO", "DY", "HR", "latitude", "longitude", "VoyageFrom", "VoyageTo", "AnchorPlace"]
PLACE_COLS = ["VoyageFrom", "VoyageTo", "AnchorPlace"]


def group_key(name):
    s = unicodedata.normalize("NFKD", name.upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Z0-9()' ]+", " ", s)
    s = re.sub(r"^THE\s+", "", re.sub(r"\s+", " ", s).strip())
    return s


def median_point(lats, lons):
    """Median lat and circular-safe median lon (handles the date line)."""
    lats = pd.to_numeric(lats, errors="coerce")
    lons = pd.to_numeric(lons, errors="coerce")
    ok = lats.notna() & lons.notna()
    if not ok.any():
        return None, None, 0
    lat, lon = lats[ok], lons[ok]
    ref = math.degrees(math.atan2(lon.map(lambda x: math.sin(math.radians(x))).mean(),
                                  lon.map(lambda x: math.cos(math.radians(x))).mean()))
    shifted = ((lon - ref + 180) % 360) - 180
    med_lon = ((shifted.median() + ref + 180) % 360) - 180
    return round(lat.median(), 2), round(med_lon, 2), int(ok.sum())


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    df = pd.read_csv(CSV_IN, usecols=COLS, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    for c in PLACE_COLS:
        df[c] = df[c].str.strip().str.replace(r"\s+", " ", regex=True)
    for c in ["YR", "MO", "DY", "HR"]:
        df[c + "_n"] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["voyage"] = df.InstAbbr + "|" + df.LogbookIdent + "|" + df.VoyageFrom + "|" + df.VoyageTo
    df = df.sort_values(["voyage", "YR_n", "MO_n", "DY_n", "HR_n"])

    has_pos = df.latitude.str.strip().ne("") & df.longitude.str.strip().ne("")
    first_fix = df[has_pos].groupby("voyage").head(1)
    last_fix = df[has_pos].groupby("voyage").tail(1)

    places = sorted((set(df.VoyageFrom) | set(df.VoyageTo) | set(df.AnchorPlace)) - {""})
    rows = []
    for place in places:
        f = df[df.VoyageFrom == place]
        t = df[df.VoyageTo == place]
        a = df[df.AnchorPlace == place]
        both = pd.concat([f, t, a])
        voyages = both.drop_duplicates("voyage")
        years = pd.to_numeric(both.YR, errors="coerce").dropna()
        dep_lat, dep_lon, dep_n = median_point(first_fix[first_fix.VoyageFrom == place].latitude,
                                               first_fix[first_fix.VoyageFrom == place].longitude)
        arr_lat, arr_lon, arr_n = median_point(last_fix[last_fix.VoyageTo == place].latitude,
                                               last_fix[last_fix.VoyageTo == place].longitude)
        anc_lat, anc_lon, anc_n = median_point(a.latitude, a.longitude)
        rows.append({
            "place": place,
            "group_key": group_key(place),
            "uncertain": "?" in place,   # transcriber marked the name as doubtful
            "rows_from": len(f),
            "rows_to": len(t),
            "rows_anchor": len(a),
            "voyages": len(voyages),
            "languages": ", ".join(sorted(set(both.LogbookLanguage) - {""})),
            "nationalities": ", ".join(sorted(set(both.Nationality) - {""})),
            "first_year": int(years.min()) if len(years) else None,
            "last_year": int(years.max()) if len(years) else None,
            "example_ships": ", ".join(voyages.ShipName.str.strip().replace("", pd.NA).dropna().unique()[:3]),
            "departure_hint_lat": dep_lat, "departure_hint_lon": dep_lon, "departure_hint_voyages": dep_n,
            "arrival_hint_lat": arr_lat, "arrival_hint_lon": arr_lon, "arrival_hint_voyages": arr_n,
            "anchor_hint_lat": anc_lat, "anchor_hint_lon": anc_lon, "anchor_hint_rows": anc_n,
        })
    out = pd.DataFrame(rows)
    out.insert(0, "place_id", range(1, len(out) + 1))
    out["group_size"] = out.groupby("group_key").place.transform("count")
    out = out.sort_values("voyages", ascending=False)
    out.to_csv(CSV_OUT, index=False, encoding="utf-8-sig")
    print(f"Wrote {CSV_OUT}: {len(out):,} places as written, {out.group_key.nunique():,} after folding variants.")


if __name__ == "__main__":
    main()
