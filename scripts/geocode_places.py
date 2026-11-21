"""Geocode the places in data/voyage_places.csv.

    python scripts/geocode_places.py interpret   # Claude: type, modern name, country, search terms
    python scripts/geocode_places.py lookup      # GeoNames (throttled), OpenStreetMap fallback
    python scripts/geocode_places.py resolve     # score candidates, flag doubtful ones, write outputs
    python scripts/geocode_places.py status

Works on group_key (spelling variants share one result). Every API response
is cached in data/geocode_cache.sqlite, so steps can be stopped and re-run.

Outputs:
    data/voyage_places_geocoded.csv   one row per place as written (join on `place`)
    data/voyage_places_review.csv     flagged places, most-used first
    data/place_overrides.csv          hand corrections; always win over automatic results
"""
import argparse
import json
import math
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from build_place_table import group_key

ROOT = Path(__file__).resolve().parent.parent
PLACES_CSV = ROOT / "data" / "voyage_places.csv"
OUT_CSV = ROOT / "data" / "voyage_places_geocoded.csv"
REVIEW_CSV = ROOT / "data" / "voyage_places_review.csv"
OVERRIDES_CSV = ROOT / "data" / "place_overrides.csv"
DB_PATH = ROOT / "data" / "geocode_cache.sqlite"

MODEL = "claude-sonnet-5-5"
GEONAMES_USER = os.environ.get("GEONAMES_USERNAME", "")
GEONAMES_HOURLY_CAP = 950          # free accounts allow 1,000 credits per hour
USER_AGENT = "cliwoc-explorer-geocoder/0.1"
ITEMS_PER_REQUEST = 40

TYPES = ["port", "roadstead", "island", "cape_or_strait", "coast_or_region", "country", "at_sea", "unclear"]
AREA_TYPES = {"coast_or_region", "country"}
# Override-only types: the name is not a place (a ship, a fleet position, a generic word)
# or lists several stops; these never get coordinates.
NO_COORD_TYPES = {"at_sea", "not_a_place", "itinerary"}
OVERRIDE_COLS = ["place", "applies_to", "lat", "lon", "place_type", "modern_name", "country_code",
                 "precision", "confidence", "note"]
# GeoNames feature classes that suit each place type.
FEATURE_CLASSES = {
    "port": ["P", "H", "S"], "roadstead": ["H", "P", "T"], "island": ["T", "L"],
    "cape_or_strait": ["T", "H"], "coast_or_region": ["L", "T", "A", "H"], "country": ["A"],
    "unclear": [],
}
MAX_HINT_KM = 300                  # flag if further than this from the anchor hint (logged while anchored there)
MIN_SCORE = 3                      # below this the best gazetteer hit is usually a fuzzy-matched namesake
MAX_TRACK_HINT_KM = 1000           # ...or from the arrival/departure hints, which are often far out at sea
MAX_GUESS_KM = 150                 # flag if gazetteer and Claude disagree by more than this

SYSTEM_PROMPT = f"""You identify places named in 17th-19th century ships' logbooks (the CLIWOC database) so they can be geocoded with a gazetteer.

Each item is a place name as transcribed (in capitals, often in old Dutch, Spanish, French or English spelling), with context: logbook languages, ship nationalities, years, example ships, other spellings, and position hints from the ship tracks. Hints: "anchor" is the median position logged while anchored there (usually within a few km); "arrival" is the median last logged position of voyages ending there (usually close); "departure" is the median first logged position of voyages leaving it (often far out at sea, because logs start after leaving). Positions are decimal degrees, west and south negative.

For each item return:
- place_type: one of {", ".join(TYPES)}. "roadstead" covers anchorages, roads and bays used as anchorages (Spithead, the Downs, Table Bay). "coast_or_region" covers coasts, regions, large islands groups and seas (Java, Bengal, Guinea coast, West Indies). "at_sea" covers cruising areas or positions at sea ("cruising western approaches", "off Newfoundland"). Use "unclear" only if you cannot tell.
- modern_name: the place's usual modern name in English (BATAVIA = Jakarta, KAAP DE GOEDE HOOP = Cape of Good Hope). Empty for at_sea.
- country_code: ISO 3166-1 alpha-2 code of the modern country containing it, empty if none or several.
- queries: 1 to 3 search strings for a gazetteer such as GeoNames, best first: the modern name, then the historical or local name if different. No country names inside the query.
- lat, lon: your best estimate of its coordinates, or null if you cannot estimate. For a roadstead use the anchorage; for a country or region use its approximate centre.
- note: a few words only if something is uncertain or notable, otherwise empty.

Use the context to choose between places with the same name (e.g. a St Johns in Antigua vs Newfoundland, a Spanish Cartagena vs a Colombian one).
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "place_type": {"type": "string", "enum": TYPES},
            "modern_name": {"type": "string"},
            "country_code": {"type": "string"},
            "queries": {"type": "array", "items": {"type": "string"}},
            "lat": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "lon": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "note": {"type": "string"},
        },
        "required": ["id", "place_type", "modern_name", "country_code", "queries", "lat", "lon", "note"],
        "additionalProperties": False,
    }}},
    "required": ["items"],
    "additionalProperties": False,
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS interpret (group_key TEXT PRIMARY KEY, result TEXT, model TEXT, at TEXT);
        CREATE TABLE IF NOT EXISTS lookups (source TEXT, query TEXT, params TEXT, response TEXT, at TEXT,
                                            PRIMARY KEY (source, query, params));
        CREATE TABLE IF NOT EXISTS geonames_calls (at REAL);
        CREATE TABLE IF NOT EXISTS usage (input INTEGER, output INTEGER, cache_read INTEGER, cache_write INTEGER, at TEXT);
    """)
    return db


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(a)))


def load_groups():
    """One record per group_key with the context Claude and the resolver need."""
    p = pd.read_csv(PLACES_CSV, encoding="utf-8-sig", keep_default_na=False)
    groups = []
    for key, g in p.groupby("group_key", sort=False):
        g = g.sort_values("voyages", ascending=False)
        top = g.iloc[0]

        def hint(prefix, count_col):
            rows = g[pd.to_numeric(g[count_col], errors="coerce").fillna(0) > 0]
            if rows.empty:
                return None
            r = rows.iloc[0]
            return {"lat": float(r[f"{prefix}_hint_lat"]), "lon": float(r[f"{prefix}_hint_lon"]), "n": int(r[count_col])}

        groups.append({
            "group_key": key,
            "name": top.place,
            "spellings": list(g.place),
            "voyages": int(g.voyages.sum()),
            "uncertain": bool(g.uncertain.astype(str).str.lower().eq("true").any()),
            "languages": top.languages, "nationalities": top.nationalities,
            "years": f"{top.first_year}-{top.last_year}", "ships": top.example_ships,
            "hints": {k: v for k, v in {
                "anchor": hint("anchor", "anchor_hint_rows"),
                "arrival": hint("arrival", "arrival_hint_voyages"),
                "departure": hint("departure", "departure_hint_voyages"),
            }.items() if v},
        })
    return groups


# -------------------------------------------------------------------- interpret

def cmd_interpret(args):
    import anthropic
    db = connect()
    done = {r[0] for r in db.execute("SELECT group_key FROM interpret")}
    todo = [g for g in load_groups() if g["group_key"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("Everything is interpreted.")
        return
    chunks = [todo[i:i + ITEMS_PER_REQUEST] for i in range(0, len(todo), ITEMS_PER_REQUEST)]
    print(f"Interpreting {len(todo):,} places in {len(chunks)} requests with {MODEL}...")
    client = anthropic.Anthropic()

    def run(chunk):
        items = [{"id": str(i), "name": g["name"], "other_spellings": [s for s in g["spellings"] if s != g["name"]],
                  "logbook_languages": g["languages"], "nationalities": g["nationalities"], "years": g["years"],
                  "example_ships": g["ships"], "hints": g["hints"]} for i, g in enumerate(chunk)]
        msg = client.messages.create(
            model=MODEL, max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": json.dumps({"items": items}, ensure_ascii=False)}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        )
        return chunk, msg

    ok = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for n, (chunk, msg) in enumerate(pool.map(run, chunks), 1):
            u = msg.usage
            db.execute("INSERT INTO usage VALUES (?,?,?,?,?)", (u.input_tokens, u.output_tokens,
                       u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0, now()))
            if msg.stop_reason != "end_turn":
                print(f"  request {n}: stopped ({msg.stop_reason}), will retry on the next run")
                db.commit()
                continue
            text = next((b.text for b in msg.content if b.type == "text"), "")
            results = {r["id"]: r for r in json.loads(text)["items"]}
            for i, g in enumerate(chunk):
                r = results.get(str(i))
                if r:
                    db.execute("INSERT OR REPLACE INTO interpret VALUES (?,?,?,?)",
                               (g["group_key"], json.dumps(r, ensure_ascii=False), MODEL, now()))
                    ok += 1
            db.commit()
            print(f"  {n}/{len(chunks)} done")
    print(f"{ok:,} places interpreted.")
    cmd_status(args, db)


# ----------------------------------------------------------------------- lookup

def http_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cached(db, source, query, params):
    r = db.execute("SELECT response FROM lookups WHERE source=? AND query=? AND params=?",
                   (source, query, params)).fetchone()
    return json.loads(r[0]) if r else None


def geonames(db, query, classes):
    params = ",".join(classes)
    hit = cached(db, "geonames", query, params)
    if hit is not None:
        return hit
    # Stay under the hourly credit limit.
    while True:
        cutoff = time.time() - 3600
        db.execute("DELETE FROM geonames_calls WHERE at < ?", (cutoff,))
        used = db.execute("SELECT COUNT(*), MIN(at) FROM geonames_calls").fetchone()
        if used[0] < GEONAMES_HOURLY_CAP:
            break
        wait = used[1] + 3600 - time.time() + 5
        print(f"  GeoNames hourly limit reached, waiting {wait / 60:.0f} min...", flush=True)
        time.sleep(max(wait, 30))
    if not GEONAMES_USER:
        raise SystemExit("Set the GEONAMES_USERNAME environment variable to your GeoNames username")
    q = [("q", query), ("maxRows", "10"), ("style", "MEDIUM"), ("username", GEONAMES_USER)]
    q += [("featureClass", c) for c in classes]
    data = http_json("http://api.geonames.org/searchJSON?" + urllib.parse.urlencode(q))
    db.execute("INSERT INTO geonames_calls VALUES (?)", (time.time(),))
    if "status" in data:
        raise RuntimeError(f"GeoNames error: {data['status'].get('message')}")
    result = [{"name": r.get("name"), "lat": float(r["lat"]), "lon": float(r["lng"]), "fcl": r.get("fcl"),
               "fcode": r.get("fcode"), "country_code": r.get("countryCode") or "",
               "population": int(r.get("population") or 0)} for r in data.get("geonames", [])]
    db.execute("INSERT INTO lookups VALUES (?,?,?,?,?)", ("geonames", query, params, json.dumps(result), now()))
    db.commit()
    return result


def nominatim(db, query):
    hit = cached(db, "nominatim", query, "")
    if hit is not None:
        return hit
    time.sleep(1.1)  # usage policy: at most one request per second
    data = http_json("https://nominatim.openstreetmap.org/search?" +
                     urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 5, "addressdetails": 1}))
    result = [{"name": r.get("name") or r.get("display_name"), "lat": float(r["lat"]), "lon": float(r["lon"]),
               "fcl": r.get("category"), "fcode": r.get("type"),
               "country_code": (r.get("address") or {}).get("country_code", "").upper(),
               "population": 0} for r in data]
    db.execute("INSERT INTO lookups VALUES (?,?,?,?,?)", ("nominatim", query, "", json.dumps(result), now()))
    db.commit()
    return result


def cmd_lookup(args):
    db = connect()
    interp = {k: json.loads(v) for k, v in db.execute("SELECT group_key, result FROM interpret")}
    groups = [g for g in load_groups() if g["group_key"] in interp]
    todo = [(g, interp[g["group_key"]]) for g in groups if interp[g["group_key"]]["place_type"] != "at_sea"]
    print(f"Looking up {len(todo):,} places (at-sea entries skipped).")
    for n, (g, it) in enumerate(todo, 1):
        classes = FEATURE_CLASSES.get(it["place_type"], [])
        found = False
        for query in it["queries"][:3]:
            if not query.strip():
                continue
            res = geonames(db, query, classes)
            if not res and classes:
                res = geonames(db, query, [])
            found = found or bool(res)
        if not found:
            for query in it["queries"][:2]:
                if query.strip() and nominatim(db, query):
                    break
        if n % 100 == 0:
            print(f"  {n:,}/{len(todo):,}", flush=True)
    print("Lookups done.")
    cmd_status(args, db)


# ---------------------------------------------------------------------- resolve

def candidates_for(db, it):
    classes = ",".join(FEATURE_CLASSES.get(it["place_type"], []))
    out = []
    for qi, query in enumerate(it["queries"][:3]):
        for source, params in (("geonames", classes), ("geonames", ""), ("nominatim", "")):
            for rank, c in enumerate(cached(db, source, query, params) or []):
                out.append({**c, "source": source, "query": query, "rank": rank, "query_rank": qi})
    return out


def type_matches(place_type, c):
    if c["source"] != "geonames":
        return None
    return c["fcl"] in FEATURE_CLASSES.get(place_type, [])


def score(c, it, hints):
    s = 0.0
    tm = type_matches(it["place_type"], c)
    s += 2 if tm else (0 if tm is False else 1)
    if it["country_code"]:
        s += 3 if c["country_code"] == it["country_code"].upper() else -2
    if hints:
        d = min(km(c["lat"], c["lon"], h["lat"], h["lon"]) for h in hints.values())
        s += 3 if d < 100 else 2 if d < 300 else 1 if d < 800 else -1
    if it["lat"] is not None and it["lon"] is not None:
        d = km(c["lat"], c["lon"], it["lat"], it["lon"])
        s += 3 if d < 50 else 2 if d < 150 else 0 if d < 500 else -2
    s -= 0.3 * c["rank"] + 0.5 * c["query_rank"]
    s += min(math.log10(c["population"] + 1), 7) / 7
    return s


def load_overrides():
    """Hand corrections. applies_to = "group" makes a row cover every spelling in the
    place's group (CADIZ, CÁDIZ, CADIZ.); otherwise it matches the exact spelling.
    Blank lat/lon keeps the automatic coordinates, so a row can simply confirm them."""
    if not OVERRIDES_CSV.exists():
        pd.DataFrame(columns=OVERRIDE_COLS).to_csv(OVERRIDES_CSV, index=False, encoding="utf-8-sig")
    o = pd.read_csv(OVERRIDES_CSV, encoding="utf-8-sig", keep_default_na=False, dtype=str)
    for c in OVERRIDE_COLS:
        if c not in o.columns:
            o[c] = ""
    exact = {r.place: r for r in o.itertuples() if r.applies_to.strip().lower() != "group"}
    group = {group_key(r.place): r for r in o.itertuples() if r.applies_to.strip().lower() == "group"}
    return exact, group


def cmd_resolve(args):
    db = connect()
    interp = {k: json.loads(v) for k, v in db.execute("SELECT group_key, result FROM interpret")}
    exact_overrides, group_overrides = load_overrides()
    places = pd.read_csv(PLACES_CSV, encoding="utf-8-sig", keep_default_na=False)
    resolved = {}
    for g in load_groups():
        it = interp.get(g["group_key"])
        if it is None:
            resolved[g["group_key"]] = {"flag_reason": "not interpreted yet"}
            continue
        # Countries and regions get a centroid, so ship positions say nothing about them.
        hints = {} if it["place_type"] in AREA_TYPES else g["hints"]
        r = {"place_type": it["place_type"], "modern_name": it["modern_name"], "country_code": it["country_code"],
             "lat": None, "lon": None, "precision": "none", "source": "", "matched_name": "",
             "confidence": "", "flag_reason": "", "note": it["note"]}
        flags = []
        if it["place_type"] == "at_sea":
            r["confidence"] = "high"
            resolved[g["group_key"]] = r
            continue
        cands = candidates_for(db, it)
        if cands:
            best = max(cands, key=lambda c: score(c, it, hints))
        if cands and score(best, it, hints) < MIN_SCORE:
            weak = f"(weak gazetteer hit: {best['name']}, {best['country_code'] or '?'})"
            if it["lat"] is not None:
                r.update(lat=round(it["lat"], 4), lon=round(it["lon"], 4), source="claude", matched_name=weak)
                flags.append("no confident gazetteer match, Claude's estimate")
            else:
                r["matched_name"] = weak
                flags.append("not found")
            cands = []
        elif cands:
            r.update(lat=round(best["lat"], 4), lon=round(best["lon"], 4), source=best["source"],
                     matched_name=best["name"] or "")
            # Gazetteer and Claude disagree on both distance and country: the gazetteer
            # probably matched a namesake (DUINS -> Glen of the Downs, Ireland), so use
            # Claude's estimate if it sits closer to the ship tracks.
            if (it["lat"] is not None and it["country_code"] and best["country_code"]
                    and best["country_code"] != it["country_code"].upper()
                    and km(best["lat"], best["lon"], it["lat"], it["lon"]) > MAX_GUESS_KM):
                guess = {"lat": it["lat"], "lon": it["lon"]}
                d_guess = min((km(guess["lat"], guess["lon"], h["lat"], h["lon"]) for h in hints.values()), default=0)
                d_best = min((km(best["lat"], best["lon"], h["lat"], h["lon"]) for h in hints.values()), default=1)
                if d_guess < d_best:
                    r.update(lat=round(it["lat"], 4), lon=round(it["lon"], 4), source="claude",
                             matched_name=f"(gazetteer offered {best['name']}, {best['country_code']})")
                    best = None
                    flags.append("gazetteer matched a namesake elsewhere; Claude's estimate")
            if best is not None:
                d_anchor = km(best["lat"], best["lon"], hints["anchor"]["lat"], hints["anchor"]["lon"]) if "anchor" in hints else None
                track = [h for k, h in hints.items() if k != "anchor"]
                if d_anchor is not None and d_anchor > MAX_HINT_KM:
                    flags.append(f"{d_anchor:,.0f} km from where ships anchored there")
                elif d_anchor is None and track:
                    d = min(km(best["lat"], best["lon"], h["lat"], h["lon"]) for h in track)
                    if d > MAX_TRACK_HINT_KM:
                        flags.append(f"{d:,.0f} km from ship-track hints")
            if best is not None and it["lat"] is not None:
                d = km(best["lat"], best["lon"], it["lat"], it["lon"])
                if d > MAX_GUESS_KM:
                    flags.append(f"gazetteer and Claude {d:,.0f} km apart")
            if best is not None and it["country_code"] and best["country_code"] and best["country_code"] != it["country_code"].upper():
                flags.append("country differs")
        elif it["lat"] is not None:
            r.update(lat=round(it["lat"], 4), lon=round(it["lon"], 4), source="claude")
            flags.append("no gazetteer match, Claude's estimate")
        elif "not found" not in flags:
            flags.append("not found")
        if it["place_type"] == "unclear":
            flags.append("type unclear")
        if r["lat"] is not None:
            r["precision"] = "area" if it["place_type"] in AREA_TYPES else ("approximate" if flags else "exact")
        r["confidence"] = "low" if len(flags) > 1 or "not found" in flags else ("medium" if flags else "high")
        r["flag_reason"] = "; ".join(flags)
        resolved[g["group_key"]] = r

    cols = ["place_type", "modern_name", "country_code", "lat", "lon", "precision", "source", "matched_name",
            "confidence", "flag_reason", "note"]
    rows = []
    for p in places.itertuples():
        r = dict(resolved.get(p.group_key, {}))
        o = exact_overrides.get(p.place) or group_overrides.get(p.group_key)
        if o is not None:
            moved = o.lat != "" and o.lon != ""
            for k in ["lat", "lon", "place_type", "modern_name", "country_code", "note"]:
                v = getattr(o, k)
                if v != "":
                    r[k] = float(v) if k in ("lat", "lon") else v
            if r.get("place_type") in NO_COORD_TYPES:
                r.update(lat=None, lon=None)
            has = r.get("lat") not in (None, "")
            r.update(source="override" if moved or not has else (r.get("source") or "override") + " (confirmed)",
                     flag_reason="", confidence=o.confidence or "high",
                     precision=o.precision or ("none" if not has else
                                               "area" if r.get("place_type") in AREA_TYPES else "exact"))
        elif "?" in p.place and r.get("place_type") not in (None, "at_sea"):
            # The transcriber doubted this spelling; the rest of its group may be fine.
            r["flag_reason"] = "; ".join(x for x in [r.get("flag_reason", ""), "name marked uncertain"] if x)
            r["confidence"] = {"high": "medium"}.get(r.get("confidence"), "low")
            if r.get("precision") == "exact":
                r["precision"] = "approximate"
        rows.append({"place": p.place, "group_key": p.group_key, "voyages": p.voyages,
                     **{c: r.get(c, "") for c in cols}})
    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    review = out[out.flag_reason != ""].drop_duplicates("group_key").sort_values("voyages", ascending=False)
    review.to_csv(REVIEW_CSV, index=False, encoding="utf-8-sig")
    print(f"Wrote {OUT_CSV} ({len(out):,} places)")
    print(f"Wrote {REVIEW_CSV} ({len(review):,} flagged groups)")
    print(out.drop_duplicates("group_key").groupby(["precision", "confidence"]).size().to_string())


# ----------------------------------------------------------------------- status

def cmd_status(args, db=None):
    db = db or connect()
    n_groups = len(load_groups())
    n_int = db.execute("SELECT COUNT(*) FROM interpret").fetchone()[0]
    print(f"\nInterpreted: {n_int:,} of {n_groups:,} place groups")
    for src, n in db.execute("SELECT source, COUNT(*) FROM lookups GROUP BY source"):
        print(f"  cached {src} lookups: {n:,}")
    i, o, cr, cw = db.execute("SELECT COALESCE(SUM(input),0), COALESCE(SUM(output),0), COALESCE(SUM(cache_read),0),"
                              " COALESCE(SUM(cache_write),0) FROM usage").fetchone()
    print(f"Claude spend: ${(i * 2 + o * 10 + cr * 0.1 + cw * 2.5) / 1e6:.2f}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    si = sub.add_parser("interpret")
    si.add_argument("--limit", type=int)
    sub.add_parser("lookup")
    sub.add_parser("resolve")
    sub.add_parser("status")
    args = p.parse_args()
    {"interpret": cmd_interpret, "lookup": cmd_lookup, "resolve": cmd_resolve, "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    main()
