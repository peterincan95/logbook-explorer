"""Export the slim data files the web app loads (app/public/data/).

The map draws and filters every positioned logbook point in the browser, so it
only gets the few fields the filters need. Rebuild after changing the logbook
or the locations (run build_locations.py first if places changed):

    python scripts/build_web_data.py

Writes:
- points.csv: one row per logbook row with a position, from MIN_YEAR on, with
  the fields the filters use plus ship name and date for the hover tooltip.
  point_id is the row number in cliwoc_points_en.csv (1-based), the same as OBJECTID in
  gis/cliwoc_explorer.gdb, so a point can be looked up in the full record.
- search.tsv: row number in points.csv (1-based, which is the object ID the
  map's CSVLayer gives each point) and the lowercased English text of that
  row's memo and weather fields, for keyword and free-text
  search. Rows with no text are left out. Loaded only when searching.
- locations.json: every location used as a voyage origin or destination.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
LOG_CSV = ROOT / "data" / "cliwoc_points_en.csv"
LOCATIONS_CSV = ROOT / "data" / "locations.csv"
CROSSWALK_CSV = ROOT / "data" / "place_to_location.csv"
OUT = ROOT / "app" / "public" / "data"

# Logbook entries before this year are left out of the web app.
MIN_YEAR = 1740

# English text searched by the keyword panel.
SEARCH_FIELDS = ["OtherShipInformation_en", "LifeOnBoard_en", "EncRem_en", "CargoMemo_en",
                 "ShipAndRigMemo_en", "BiologyMemo_en", "WarsAndFightsMemo_en", "OtherRem_en",
                 "Weather_en", "StateSea_en"]


def clean_place(s):
    return s.str.strip().str.replace(r"\s+", " ", regex=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    cols = ["latitude", "longitude", "Nationality", "Company", "YR", "MO", "DY", "ShipName", "VoyageFrom", "VoyageTo"]
    log = pd.read_csv(LOG_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False,
                      usecols=cols + SEARCH_FIELDS)
    log["point_id"] = range(1, len(log) + 1)
    ids = pd.read_csv(CROSSWALK_CSV, encoding="utf-8-sig", keep_default_na=False)
    ids = dict(zip(ids.place, ids.location_id.astype(int)))
    log["origin"] = clean_place(log.VoyageFrom).map(ids).astype("Int64")
    log["dest"] = clean_place(log.VoyageTo).map(ids).astype("Int64")

    lat = pd.to_numeric(log.latitude, errors="coerce")
    lon = pd.to_numeric(log.longitude, errors="coerce")
    pts = log[lat.notna() & lon.notna()].copy()
    pts["lat"] = lat[pts.index].round(4)
    pts["lon"] = lon[pts.index].round(4)
    pts["year"] = pd.to_numeric(pts.YR, errors="coerce").astype("Int64")
    pts["nat"] = pts.Nationality.str.strip()
    pts["company"] = pts.Company.str.strip()
    pts["ship"] = pts.ShipName.str.strip()
    # ISO date (YYYY-MM-DD) for the hover tooltip; blank if the day is missing or invalid
    ymd = pd.to_datetime(dict(year=pd.to_numeric(pts.YR, errors="coerce"),
                              month=pd.to_numeric(pts.MO, errors="coerce"),
                              day=pd.to_numeric(pts.DY, errors="coerce")), errors="coerce")
    pts["date"] = ymd.dt.strftime("%Y-%m-%d").fillna("")
    pts = pts[pts.year >= MIN_YEAR]
    pts = pts.reset_index(drop=True)
    pts[["point_id", "lon", "lat", "nat", "company", "origin", "dest", "year", "ship", "date"]].to_csv(
        OUT / "points.csv", index=False, encoding="utf-8")

    text = pts[SEARCH_FIELDS].apply(lambda r: " | ".join(x.strip() for x in r if x.strip()), axis=1)
    text = text.str.lower().str.replace(r"[\t\r\n]+", " ", regex=True)
    with open(OUT / "search.tsv", "w", encoding="utf-8", newline="\n") as f:
        has = text != ""
        for row, t in zip(text.index[has] + 1, text[has]):
            f.write(f"{row}\t{t}\n")

    locs = pd.read_csv(LOCATIONS_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    used_o, used_d = set(pts.origin.dropna()), set(pts.dest.dropna())
    out = []
    for r in locs.itertuples():
        lid = int(r.location_id)
        if lid not in used_o and lid not in used_d:
            continue
        out.append({
            "id": lid, "name": r.common_name, "modern": r.modern_name,
            "names": [n for n in r.names_as_written.split(" | ") if n != r.common_name],
            "lat": float(r.lat) if r.lat else None, "lon": float(r.lon) if r.lon else None,
            "origin": int((pts.origin == lid).sum()), "dest": int((pts.dest == lid).sum()),
        })
    (OUT / "locations.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                                        encoding="utf-8")

    for name in ["points.csv", "search.tsv", "locations.json"]:
        print(f"{name}: {(OUT / name).stat().st_size / 1e6:.1f} MB")
    print(f"{len(pts):,} points, {(text != '').sum():,} with text, {len(out):,} locations")


if __name__ == "__main__":
    main()
