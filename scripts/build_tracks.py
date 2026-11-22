"""Give every logbook row a track (one ship's voyage) and its order along it,
so the points can be joined into lines (e.g. ArcGIS Pro's Points To Line with
Line Field = track_id and Sort Field = track_seq).

A track is one voyage as recorded in one logbook source:

- Rows with a voyage start date (VoyageIni) belong to the track ID + VoyageIni.
  ID identifies the ship and logbook source; VoyageIni separates the voyages
  in a logbook. track_id = "<ID>-<VoyageIni>", e.g. "45-18490807".
- Rows without VoyageIni (about 5,000) are grouped by ID, VoyageFrom and
  VoyageTo, split wherever a gap of more than GAP_DAYS falls between
  observations, and dated by their first observation: track_id =
  "<ID>-<first date>i" (i = inferred start), e.g. "512-17790304i".

track_seq numbers the rows of a track in time order (date, then hour on board
HR, then file order; the file isn't always chronological).

track_duplicate flags the same voyage keyed from more than one source
(original logbook and extracts). KNMI's ShipLogbookID file, which marked
these, isn't available any more, so they are detected here: tracks of the
same ship with the same start date but different IDs. The one with the most
positioned points gets 0, the others 1, 2, ... in order of size. Tracks with
no such twin are 0. Filter on track_duplicate = 0 to drop the copies.

Also writes data/tracks.csv, one row per track, for checking.

    python scripts/build_tracks.py      (writes data/tracks.csv only)
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
LOG_CSV = ROOT / "data" / "cliwoc_points_en.csv"
TRACKS_CSV = ROOT / "data" / "tracks.csv"
GAP_DAYS = 30
COLS = ["ID", "VoyageIni", "VoyageFrom", "VoyageTo", "ShipName", "YR", "MO", "DY", "HR", "latitude", "longitude"]


def _date(df):
    return pd.to_datetime(dict(year=pd.to_numeric(df.YR, errors="coerce"),
                               month=pd.to_numeric(df.MO, errors="coerce"),
                               day=pd.to_numeric(df.DY, errors="coerce")), errors="coerce")


def assign_tracks(log):
    """log: DataFrame with COLS as strings, in file order. Returns a DataFrame
    (same index) with track_id, track_seq, track_duplicate, plus the per-track
    summary table."""
    df = log[COLS].copy()
    df["row"] = range(len(df))
    df["date"] = _date(df)
    hr = pd.to_numeric(df.HR, errors="coerce")
    df["hour"] = hr.where((hr >= 0) & (hr < 2400))
    df["has_pos"] = (df.latitude.str.strip() != "") & (df.longitude.str.strip() != "")
    for c in ["ID", "VoyageIni", "VoyageFrom", "VoyageTo", "ShipName"]:
        df[c] = df[c].str.strip()

    df["track_id"] = df.ID + "-" + df.VoyageIni
    df["inferred"] = df.VoyageIni == ""

    # Undated rows: ID + route, split at long gaps, named after the first date
    und = df[df.inferred].sort_values(["ID", "VoyageFrom", "VoyageTo", "date", "hour", "row"])
    if len(und):
        grp = und.ID + "|" + und.VoyageFrom + "|" + und.VoyageTo
        gap = und.groupby(grp).date.diff().dt.days.fillna(0) > GAP_DAYS
        part = gap.groupby(grp).cumsum()
        first = und.groupby([grp, part]).date.transform("min")
        name = und.ID + "-" + first.dt.strftime("%Y%m%d").fillna("00000000") + "i"
        # Two undated groups of the same ship starting the same day: number them
        key = grp + "|" + part.astype(str)
        clash = name.groupby(name).transform(lambda s: key[s.index].nunique() > 1)
        if clash.any():
            n = key[clash].groupby(name[clash]).rank(method="dense").astype(int)
            name[clash] = name[clash] + n.astype(str)
        df.loc[und.index, "track_id"] = name

    # Order along each track
    df = df.sort_values(["track_id", "date", "hour", "row"])
    df["track_seq"] = df.groupby("track_id").cumcount() + 1
    df = df.sort_values("row")

    # Summary per track
    t = df.groupby("track_id").agg(
        ID=("ID", "first"), ship=("ShipName", "first"), voyage_ini=("VoyageIni", "first"),
        start_inferred=("inferred", "first"), first_date=("date", "min"), last_date=("date", "max"),
        voyage_from=("VoyageFrom", lambda s: s.mode().iat[0] if len(s.mode()) else ""),
        voyage_to=("VoyageTo", lambda s: s.mode().iat[0] if len(s.mode()) else ""),
        rows=("row", "size"), positioned=("has_pos", "sum")).reset_index()
    t["start"] = t.voyage_ini.where(t.voyage_ini != "", t.first_date.dt.strftime("%Y%m%d"))

    # Likely duplicates: same ship and start date, different ID
    t = t.sort_values(["ship", "start", "positioned", "rows", "track_id"], ascending=[True, True, False, False, True])
    t["track_duplicate"] = t.groupby(["ship", "start"]).cumcount()
    t.loc[t.ship == "", "track_duplicate"] = 0
    df["track_duplicate"] = df.track_id.map(dict(zip(t.track_id, t.track_duplicate)))

    t["first_date"] = t.first_date.dt.strftime("%Y-%m-%d")
    t["last_date"] = t.last_date.dt.strftime("%Y-%m-%d")
    t = t.sort_values("track_id", key=lambda s: s.str.split("-").map(lambda p: (int(p[0]) if p[0].isdigit() else 0, p[1])))
    t = t[["track_id", "ID", "ship", "voyage_ini", "start_inferred", "first_date", "last_date",
           "voyage_from", "voyage_to", "rows", "positioned", "track_duplicate"]]
    return df[["track_id", "track_seq", "track_duplicate"]], t


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    log = pd.read_csv(LOG_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False, usecols=COLS)
    rows, tracks = assign_tracks(log)
    tracks.to_csv(TRACKS_CSV, index=False, encoding="utf-8-sig")
    dup = tracks.track_duplicate > 0
    print(f"{len(tracks):,} tracks ({tracks.start_inferred.sum():,} with inferred start, "
          f"{dup.sum():,} likely duplicates) -> {TRACKS_CSV.name}")
    return rows, tracks


if __name__ == "__main__":
    main()
