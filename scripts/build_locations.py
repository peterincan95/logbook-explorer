"""Collapse geocoded place names into one record per location.

Several spellings and names often resolve to the same point (CADIZ, CÁDIZ,
CADIX; TABLE BAY, KAAPSTAD). This merges every place name with identical
coordinates into one location. Names without coordinates (at sea, not a
place, not found) are merged by their folded spelling (group_key) instead.

Writes:
- data/locations.csv: one row per location (location_id is the key)
- data/place_to_location.csv: every place name as written -> location_id,
  used to give each logbook row its origin/destination/anchor location

Usage counts are recomputed per location from the logbook, so a voyage that
mentions a location under two spellings is counted once.

Location IDs are stable across rebuilds. data/location_ids.json records the
ID each place name was given; on a rebuild every location takes the ID most
of its names (weighted by voyages) already had, so moving a location, adding
a spelling or changing an override keeps its ID. When two locations merge,
the larger keeps its ID; when one splits, the larger part keeps it and the
rest get new IDs. New IDs continue from the highest ever issued, so a
retired ID is never reused.

    python scripts/build_locations.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
GEOCODED_CSV = ROOT / "data" / "voyage_places_geocoded.csv"
LOG_CSV = ROOT / "data" / "cliwoc_points.csv"
LOCATIONS_CSV = ROOT / "data" / "locations.csv"
CROSSWALK_CSV = ROOT / "data" / "place_to_location.csv"
REGISTRY_JSON = ROOT / "data" / "location_ids.json"

PLACE_COLS = {"VoyageFrom": "from", "VoyageTo": "to", "AnchorPlace": "anchor"}
# Attributes taken from the location's most-used name.
CARRIED = ["modern_name", "place_type", "country_code", "lat", "lon", "precision", "confidence",
           "source", "flag_reason", "note"]


def clean_place(s):
    """Same normalisation build_place_table.py used when it listed the places."""
    return s.str.strip().str.replace(r"\s+", " ", regex=True)


def load_registry():
    if REGISTRY_JSON.exists():
        reg = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))
        return reg["next_id"], {k: int(v) for k, v in reg["ids"].items()}
    if CROSSWALK_CSV.exists():
        # First run with the registry: keep the IDs already handed out.
        x = pd.read_csv(CROSSWALK_CSV, encoding="utf-8-sig", keep_default_na=False)
        ids = dict(zip(x.place, x.location_id.astype(int)))
        return max(ids.values()) + 1, ids
    return 1, {}


def save_registry(next_id, ids):
    REGISTRY_JSON.write_text(json.dumps({"next_id": next_id, "ids": dict(sorted(ids.items()))},
                                        ensure_ascii=False, indent=1), encoding="utf-8")


def assign_ids(members, order, next_id, ids):
    """members: merge_key -> [(place, voyages)]; order: merge_keys, largest first.
    Returns merge_key -> location_id plus the updated registry."""
    taken, out = set(), {}
    for key in order:
        votes = Counter()
        for place, voyages in members[key]:
            if place in ids:
                votes[ids[place]] += voyages + 1      # +1 so unused names still vote
        choice = next((i for i, _ in votes.most_common() if i not in taken), None)
        if choice is None:
            choice, next_id = next_id, next_id + 1
        taken.add(choice)
        out[key] = choice
    ids = dict(ids)
    for key, lid in out.items():
        for place, _ in members[key]:
            ids[place] = lid
    next_id = max([next_id] + [i + 1 for i in out.values()])
    return out, next_id, ids


def build():
    geo = pd.read_csv(GEOCODED_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    geo["voyages"] = pd.to_numeric(geo.voyages).fillna(0).astype(int)
    has = (geo.lat != "") & (geo.lon != "")
    geo["merge_key"] = "name:" + geo.group_key
    geo.loc[has, "merge_key"] = ("xy:" + geo.loc[has, "lat"].astype(float).round(4).astype(str) + ","
                                 + geo.loc[has, "lon"].astype(float).round(4).astype(str))

    log = pd.read_csv(LOG_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False,
                      usecols=["InstAbbr", "LogbookIdent", "LogbookLanguage", "Nationality", "YR"] + list(PLACE_COLS))
    for c in PLACE_COLS:
        log[c] = clean_place(log[c])
    log["voyage"] = log.InstAbbr + "|" + log.LogbookIdent + "|" + log.VoyageFrom + "|" + log.VoyageTo
    to_key = dict(zip(geo.place, geo.merge_key))

    # Long table: one row per (logbook row, role) that names a place.
    parts = []
    for col, role in PLACE_COLS.items():
        p = log[log[col] != ""][["voyage", "LogbookLanguage", "Nationality", "YR"]].copy()
        p["merge_key"] = log.loc[p.index, col].map(to_key)
        p["role"] = role
        parts.append(p)
    uses = pd.concat(parts)
    missing = uses.merge_key.isna().sum()
    if missing:
        raise SystemExit(f"{missing} logbook place names are missing from {GEOCODED_CSV.name}; re-run the place steps")
    uses["YR"] = pd.to_numeric(uses.YR, errors="coerce")

    counts = uses.groupby("merge_key").agg(
        voyages=("voyage", "nunique"), first_year=("YR", "min"), last_year=("YR", "max"),
        languages=("LogbookLanguage", lambda s: ", ".join(sorted(set(s) - {""}))),
        nationalities=("Nationality", lambda s: ", ".join(sorted(set(s) - {""}))))
    for role in PLACE_COLS.values():
        counts[f"rows_{role}"] = uses[uses.role == role].groupby("merge_key").size()
    counts = counts.fillna({f"rows_{r}": 0 for r in PLACE_COLS.values()})

    geo = geo.sort_values(["merge_key", "voyages", "place"], ascending=[True, False, True])
    locs = geo.groupby("merge_key", sort=False).agg(
        common_name=("place", "first"),
        names_as_written=("place", lambda s: " | ".join(s)),
        name_count=("place", "size"),
        **{c: (c, "first") for c in CARRIED})
    locs = locs.join(counts).reset_index()
    locs = locs.sort_values(["voyages", "common_name"], ascending=[False, True]).reset_index(drop=True)
    members = {k: list(zip(g.place, g.voyages)) for k, g in geo.groupby("merge_key", sort=False)}
    next_id, ids = load_registry()
    key_to_id, next_id, ids = assign_ids(members, list(locs.merge_key), next_id, ids)
    locs.insert(0, "location_id", locs.merge_key.map(key_to_id))
    locs = locs.sort_values("location_id").reset_index(drop=True)
    for c in ["voyages", "rows_from", "rows_to", "rows_anchor", "first_year", "last_year"]:
        locs[c] = locs[c].astype("Int64")

    cols = ["location_id", "common_name", "modern_name", "place_type", "country_code", "lat", "lon",
            "precision", "confidence", "source", "flag_reason", "note", "voyages", "rows_from", "rows_to",
            "rows_anchor", "first_year", "last_year", "languages", "nationalities", "name_count",
            "names_as_written"]
    locs = locs[cols + ["merge_key"]]
    crosswalk = geo[["place"]].assign(location_id=geo.merge_key.map(dict(zip(locs.merge_key, locs.location_id))))
    crosswalk = crosswalk.sort_values("place").reset_index(drop=True)
    locs = locs[cols]

    locs.to_csv(LOCATIONS_CSV, index=False, encoding="utf-8-sig")
    save_registry(next_id, ids)
    crosswalk.to_csv(CROSSWALK_CSV, index=False, encoding="utf-8-sig")
    print(f"Wrote {LOCATIONS_CSV.name}: {len(locs):,} locations from {len(geo):,} place names "
          f"({(locs.lat != '').sum():,} with coordinates)")
    print(f"Wrote {CROSSWALK_CSV.name}")
    return locs, crosswalk


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    build()
