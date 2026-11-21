"""Translate CLIWOC memo and weather fields into English.

Every unique (language, field, text) phrase is translated once and stored in a
SQLite cache; the output CSV is then built by looking each cell up in it.

    python scripts/translate_logs.py extract       # find phrases, apply rules (no API)
    python scripts/translate_logs.py pilot --n 300 # translate a sample, write a review CSV
    python scripts/translate_logs.py submit        # send everything pending as a Message Batch
    python scripts/translate_logs.py collect       # fetch finished batch results (--wait to poll)
    python scripts/translate_logs.py status        # progress and spend so far
    python scripts/translate_logs.py write         # build data/cliwoc_points_en.csv

Re-running any step is safe: phrases already in the cache are never sent again.
"""
import argparse
import json
import random
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import compass  # noqa: E402
from translation_prompt import LANGUAGE_NAMES, OUTPUT_SCHEMA, SYSTEM_PROMPT  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CSV_IN = ROOT / "data" / "cliwoc_points.csv"
CSV_OUT = ROOT / "data" / "cliwoc_points_en.csv"
DB_PATH = ROOT / "data" / "translation_cache.sqlite"
PILOT_CSV = ROOT / "data" / "translation_pilot_review.csv"

MODEL = "claude-sonnet-5-5"
EFFORT = "low"            # translation needs little reasoning; raise if the pilot shows errors
MAX_TOKENS = 16000        # thinking counts toward this
MAX_ITEMS_PER_REQUEST = 60
MAX_CHARS_PER_REQUEST = 6000
MAX_ATTEMPTS = 3

# Claude Sonnet 5.5, USD per million tokens. Batches are billed at half.
PRICE = {"input": 2.00, "output": 10.00, "cache_read": 0.10, "cache_write": 2.50}

TEXT_FIELDS = [
    "LifeOnBoard", "EncRem", "CargoMemo", "ShipAndRigMemo", "BiologyMemo",
    "WarsAndFightsMemo", "OtherRem", "OtherShipInformation",
    "Weather", "AllWindForces", "StateSea", "PrecipitationDescriptor", "ShapeClouds", "Clearness",
]
DIRECTION_FIELDS = ["AllWindDirections", "DirClouds"]
# English entries in these fields are re-cased by rule; they rarely contain proper nouns.
RULE_CASED_ENGLISH = ["Weather", "AllWindForces", "StateSea", "PrecipitationDescriptor", "ShapeClouds", "Clearness"]
ALL_FIELDS = TEXT_FIELDS + DIRECTION_FIELDS
LANG_COL = "LogbookLanguage"

CODE_RE = re.compile(r"^(?:[A-Z]\d\d[\s,;/\-]*)+$")      # Dutch symbol codes: W00, V04 ...
NUMBER_RE = re.compile(r"^[\d\s.,/\-+:()]*$")


def normalize(s):
    return re.sub(r"\s+", " ", s).strip()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def letters_only(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


COMPASS_WORD = re.compile(r"^[NESW]{1,3}(?:B[NESW]{1,2})?$")
NOT_COMPASS = {"SEE"}
CODE_WORD = re.compile(r"^[A-Z]\d\d$")


def _keep_upper(word):
    if CODE_WORD.match(word):
        return True
    if word in NOT_COMPASS or not COMPASS_WORD.match(word):
        return False
    main = word.split("B")[0]
    return not (("E" in main and "W" in main) or ("N" in main and "S" in main))


def rule_sentence_case(s):
    """Sentence case for English text: compass points, codes and AM/PM stay upper case."""
    def word(m):
        w = m.group(0)
        if _keep_upper(w):
            return w.replace("B", "b") if len(w) > 2 and "B" in w else w
        if w in ("AM", "PM"):
            return w
        return w.lower()
    out = re.sub(r"[A-Z]\w*", word, s.upper())
    out = re.sub(r"(\d)(am|pm)\b", lambda m: m.group(1) + m.group(2).upper(), out, flags=re.I)
    out = re.sub(r"\b([ap])\.m\.", lambda m: m.group(1).upper() + ".M.", out)
    out = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), out)
    return re.sub(r"\bi\b", "I", out)


# --------------------------------------------------------------------------- db

def connect():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS phrases (
            lang TEXT NOT NULL, field TEXT NOT NULL, src TEXT NOT NULL,
            en TEXT, method TEXT, status TEXT NOT NULL,
            detected_lang TEXT, model TEXT, n_rows INTEGER DEFAULT 0,
            attempts INTEGER DEFAULT 0, batch_id TEXT, updated_at TEXT,
            PRIMARY KEY (lang, field, src));
        CREATE INDEX IF NOT EXISTS phrases_status ON phrases(status);
        CREATE TABLE IF NOT EXISTS requests (
            custom_id TEXT PRIMARY KEY, batch_id TEXT, items TEXT NOT NULL, done INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS batches (
            batch_id TEXT PRIMARY KEY, created_at TEXT, n_requests INTEGER, collected INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS usage (
            custom_id TEXT, batch INTEGER, input INTEGER, output INTEGER,
            cache_read INTEGER, cache_write INTEGER, at TEXT);
    """)
    return db


# ---------------------------------------------------------------------- extract

def classify(lang, field, src):
    """Return (en, method) for phrases handled without the model, else None."""
    if CODE_RE.match(src):
        return src, "code"
    if NUMBER_RE.match(src):
        return src, "number"
    if field in DIRECTION_FIELDS:
        out = compass.convert(src, lang)
        if out is not None:
            return out, "rule"
    if lang == "ENGLISH" and field in RULE_CASED_ENGLISH:
        return rule_sentence_case(src), "recase_rule"
    return None


def cmd_extract(args):
    counts = {}
    for chunk in pd.read_csv(CSV_IN, usecols=[LANG_COL] + ALL_FIELDS, dtype=str,
                             encoding="utf-8-sig", keep_default_na=False, chunksize=50000):
        for field in ALL_FIELDS:
            for lang, text in zip(chunk[LANG_COL], chunk[field]):
                if not text.strip():
                    continue
                key = (lang, field, normalize(text))
                counts[key] = counts.get(key, 0) + 1
    db = connect()
    new = 0
    for (lang, field, src), n in counts.items():
        row = db.execute("SELECT status FROM phrases WHERE lang=? AND field=? AND src=?",
                         (lang, field, src)).fetchone()
        if row:
            db.execute("UPDATE phrases SET n_rows=? WHERE lang=? AND field=? AND src=?",
                       (n, lang, field, src))
            # Re-apply the rules to anything still waiting, in case they improved.
            done = classify(lang, field, src) if row[0] == "pending" else None
            if done:
                db.execute("UPDATE phrases SET en=?, method=?, status='done', updated_at=?"
                           " WHERE lang=? AND field=? AND src=?", (done[0], done[1], now(), lang, field, src))
            continue
        new += 1
        done = classify(lang, field, src)
        if done:
            db.execute("INSERT INTO phrases (lang, field, src, en, method, status, n_rows, updated_at)"
                       " VALUES (?,?,?,?,?,'done',?,?)", (lang, field, src, done[0], done[1], n, now()))
        else:
            db.execute("INSERT INTO phrases (lang, field, src, status, n_rows, updated_at)"
                       " VALUES (?,?,?,'pending',?,?)", (lang, field, src, n, now()))
    db.commit()
    print(f"{len(counts):,} unique phrases found, {new:,} new to the cache.")
    cmd_status(args, db)


# --------------------------------------------------------------------- requests

def build_requests(phrases):
    """Group (lang, field, src) phrases into requests: one language per request."""
    by_lang = {}
    for p in phrases:
        by_lang.setdefault(p[0], []).append(p)
    requests = []
    for lang, items in by_lang.items():
        cur, chars = [], 0
        for p in items:
            if cur and (len(cur) >= MAX_ITEMS_PER_REQUEST or chars + len(p[2]) > MAX_CHARS_PER_REQUEST):
                requests.append((lang, cur))
                cur, chars = [], 0
            cur.append(p)
            chars += len(p[2])
        if cur:
            requests.append((lang, cur))
    return requests


def request_params(lang, items):
    payload = {
        "source_language": LANGUAGE_NAMES.get(lang, lang.title()),
        "items": [{"id": str(i), "field": f, "text": s} for i, (_, f, s) in enumerate(items)],
    }
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    }


def record_usage(db, custom_id, usage, batch):
    db.execute("INSERT INTO usage VALUES (?,?,?,?,?,?,?)", (
        custom_id, int(batch), usage.input_tokens, usage.output_tokens,
        usage.cache_read_input_tokens or 0, usage.cache_creation_input_tokens or 0, now()))


def apply_result(db, items, message, batch_id=None):
    """Store one response's translations; anything unusable goes back to pending."""
    returned = {}
    if message is not None and message.stop_reason == "end_turn":
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            returned = {r["id"]: r for r in json.loads(text)["items"]}
        except (json.JSONDecodeError, KeyError, TypeError):
            returned = {}
    ok = 0
    for i, (lang, field, src) in enumerate(items):
        r = returned.get(str(i))
        en = (r or {}).get("english", "").strip()
        if not en:
            db.execute("UPDATE phrases SET attempts=attempts+1, batch_id=NULL, updated_at=?,"
                       " status=CASE WHEN attempts+1>=? THEN 'failed' ELSE 'pending' END"
                       " WHERE lang=? AND field=? AND src=?", (now(), MAX_ATTEMPTS, lang, field, src))
            continue
        method = "llm"
        if lang == "ENGLISH" and letters_only(en) != letters_only(src):
            en, method = rule_sentence_case(src), "recase_rule"   # model changed the words
        elif lang == "ENGLISH":
            method = "recase"
        db.execute("UPDATE phrases SET en=?, method=?, status='done', detected_lang=?, model=?,"
                   " batch_id=?, updated_at=? WHERE lang=? AND field=? AND src=?",
                   (en, method, r.get("source_language"), MODEL, batch_id, now(), lang, field, src))
        ok += 1
    return ok


def pending_phrases(db, limit=None):
    q = "SELECT lang, field, src FROM phrases WHERE status='pending' ORDER BY lang, field, src"
    rows = db.execute(q).fetchall()
    return rows[:limit] if limit else rows


def client():
    import anthropic
    return anthropic.Anthropic()


# ------------------------------------------------------------------------ pilot

def cmd_pilot(args):
    db = connect()
    rows = db.execute("SELECT lang, field, src, n_rows FROM phrases WHERE status='pending'").fetchall()
    if not rows:
        print("Nothing pending. Run extract first.")
        return
    rng = random.Random(args.seed)
    groups = {}
    for r in rows:
        groups.setdefault((r[0], r[1]), []).append(r)
    sample = []
    for (lang, _), g in sorted(groups.items()):
        g.sort(key=lambda r: -r[3])
        k = 2 if lang == "ENGLISH" else 4
        top = g[: k // 2]
        rest = g[k // 2:]
        sample += top + rng.sample(rest, min(len(rest), k - len(top)))
    chosen = set(sample)
    remaining = [r for r in rows if r not in chosen]
    rng.shuffle(remaining)
    sample += remaining[: max(0, args.n - len(sample))]
    sample = sample[: args.n]
    phrases = [(r[0], r[1], r[2]) for r in sample]
    reqs = build_requests(phrases)
    print(f"Translating {len(phrases)} sample phrases in {len(reqs)} requests with {MODEL}...")

    c = client()

    def run(req):
        lang, items = req
        return req, c.messages.create(**request_params(lang, items))

    usage_before = totals(db)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for n, ((lang, items), msg) in enumerate(pool.map(run, reqs), 1):
            if msg.stop_reason == "refusal":
                print(f"  request {n}: refused ({getattr(msg, 'stop_details', None)})")
            record_usage(db, f"pilot-{n}", msg.usage, batch=False)
            apply_result(db, items, msg)
            db.commit()
            print(f"  {n}/{len(reqs)} done")

    keys = set(phrases)
    out = [r for r in db.execute(
        "SELECT lang, field, n_rows, src, en, method, detected_lang FROM phrases WHERE status!='pending'")
        if (r[0], r[1], r[3]) in keys]
    pd.DataFrame(out, columns=["language", "field", "rows", "source", "english", "method", "detected"]) \
        .sort_values(["language", "field", "rows"], ascending=[True, True, False]) \
        .to_csv(PILOT_CSV, index=False, encoding="utf-8-sig")
    print(f"\nReview file: {PILOT_CSV}")

    spent = cost(totals(db), batch=False) - cost(usage_before, batch=False)
    src_chars = sum(len(p[2]) for p in phrases)
    left = db.execute("SELECT COALESCE(SUM(LENGTH(src)),0) FROM phrases WHERE status='pending'").fetchone()[0]
    print(f"Pilot cost: ${spent:.2f} for {src_chars:,} source characters.")
    if src_chars:
        print(f"Estimated full batch run ({left:,} characters left, batch price): "
              f"${spent / src_chars * left / 2:.2f}")


# ---------------------------------------------------------------- submit/collect

def cmd_submit(args):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    db = connect()
    phrases = pending_phrases(db, args.limit)
    if not phrases:
        print("Nothing pending.")
        return
    reqs = build_requests(phrases)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    batch_reqs, mapping = [], []
    for n, (lang, items) in enumerate(reqs):
        cid = f"{stamp}-{lang[:2]}-{n:05d}"
        batch_reqs.append(Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**request_params(lang, items))))
        mapping.append((cid, json.dumps(items, ensure_ascii=False)))
    if args.dry_run:
        print(f"Would submit {len(phrases):,} phrases in {len(reqs):,} requests. Nothing sent.")
        return
    batch = client().messages.batches.create(requests=batch_reqs)
    db.executemany("INSERT INTO requests (custom_id, batch_id, items) VALUES (?,?,?)",
                   [(cid, batch.id, items) for cid, items in mapping])
    db.execute("INSERT INTO batches VALUES (?,?,?,0)", (batch.id, now(), len(reqs)))
    db.executemany("UPDATE phrases SET status='in_batch', batch_id=? WHERE lang=? AND field=? AND src=?",
                   [(batch.id, *p) for p in phrases])
    db.commit()
    print(f"Submitted batch {batch.id}: {len(phrases):,} phrases in {len(reqs):,} requests.")
    print("Most batches finish within an hour. Run `collect --wait` to fetch the results.")


def cmd_collect(args):
    db = connect()
    c = client()
    while True:
        open_batches = [r[0] for r in db.execute("SELECT batch_id FROM batches WHERE collected=0")]
        if not open_batches:
            print("No open batches.")
            break
        still_running = 0
        for bid in open_batches:
            b = c.messages.batches.retrieve(bid)
            rc = b.request_counts
            if b.processing_status != "ended":
                still_running += 1
                print(f"{bid}: {b.processing_status} ({rc.processing} processing, {rc.succeeded} succeeded)")
                continue
            ok = 0
            for res in c.messages.batches.results(bid):
                row = db.execute("SELECT items, done FROM requests WHERE custom_id=?", (res.custom_id,)).fetchone()
                if not row or row[1]:
                    continue
                items = [tuple(x) for x in json.loads(row[0])]
                msg = res.result.message if res.result.type == "succeeded" else None
                if msg is not None:
                    record_usage(db, res.custom_id, msg.usage, batch=True)
                ok += apply_result(db, items, msg, bid)
                db.execute("UPDATE requests SET done=1 WHERE custom_id=?", (res.custom_id,))
            # Anything from this batch that never came back goes back to pending.
            db.execute("UPDATE phrases SET status='pending', batch_id=NULL WHERE status='in_batch' AND batch_id=?", (bid,))
            db.execute("UPDATE batches SET collected=1 WHERE batch_id=?", (bid,))
            db.commit()
            print(f"{bid}: ended. {ok:,} phrases translated "
                  f"({rc.errored} errored, {rc.expired} expired requests).")
        if not (args.wait and still_running):
            break
        time.sleep(60)
    cmd_status(args, db)


# ----------------------------------------------------------------------- status

def totals(db):
    r = db.execute("SELECT batch, COALESCE(SUM(input),0), COALESCE(SUM(output),0), COALESCE(SUM(cache_read),0),"
                   " COALESCE(SUM(cache_write),0) FROM usage GROUP BY batch").fetchall()
    return {bool(b): (i, o, cr, cw) for b, i, o, cr, cw in r}


def cost(t, batch=None):
    total = 0.0
    for is_batch, (i, o, cr, cw) in t.items():
        if batch is not None and is_batch != batch:
            continue
        usd = (i * PRICE["input"] + o * PRICE["output"] + cr * PRICE["cache_read"] + cw * PRICE["cache_write"]) / 1e6
        total += usd / 2 if is_batch else usd
    return total


def cmd_status(args, db=None):
    db = db or connect()
    print("\nPhrases by status:")
    for status, n, chars in db.execute(
            "SELECT status, COUNT(*), SUM(LENGTH(src)) FROM phrases GROUP BY status ORDER BY status"):
        print(f"  {status:10} {n:>8,}  ({chars:,} characters)")
    print("Done, by method:")
    for method, n in db.execute(
            "SELECT method, COUNT(*) FROM phrases WHERE status='done' GROUP BY method ORDER BY 2 DESC"):
        print(f"  {method:12} {n:>8,}")
    print(f"API spend so far: ${cost(totals(db)):.2f}")


# ------------------------------------------------------------------------ write

def cmd_write(args):
    db = connect()
    lookup = {(l, f, s): e for l, f, s, e in db.execute(
        "SELECT lang, field, src, en FROM phrases WHERE status='done'")}
    missing = {f: 0 for f in ALL_FIELDS}
    first = True
    with open(CSV_OUT, "w", encoding="utf-8-sig", newline="") as fh:
        for chunk in pd.read_csv(CSV_IN, dtype=str, encoding="utf-8-sig",
                                 keep_default_na=False, chunksize=20000):
            for field in ALL_FIELDS:
                en = []
                for lang, text in zip(chunk[LANG_COL], chunk[field]):
                    if not text.strip():
                        en.append("")
                        continue
                    v = lookup.get((lang, field, normalize(text)))
                    if v is None:
                        missing[field] += 1
                        v = ""
                    en.append(v)
                chunk.insert(chunk.columns.get_loc(field) + 1, f"{field}_en", en)
            chunk.to_csv(fh, index=False, header=first)
            first = False
    print(f"Wrote {CSV_OUT}")
    gaps = {f: n for f, n in missing.items() if n}
    if gaps:
        print("Cells left blank because their phrase isn't translated yet:")
        for f, n in gaps.items():
            print(f"  {f:26} {n:,}")


# ------------------------------------------------------------------------- main

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("extract")
    sp = sub.add_parser("pilot")
    sp.add_argument("--n", type=int, default=300)
    sp.add_argument("--seed", type=int, default=1)
    ss = sub.add_parser("submit")
    ss.add_argument("--limit", type=int, help="only submit the first N pending phrases")
    ss.add_argument("--dry-run", action="store_true")
    sc = sub.add_parser("collect")
    sc.add_argument("--wait", action="store_true", help="poll every minute until all batches end")
    sub.add_parser("status")
    sub.add_parser("write")
    args = p.parse_args()
    {"extract": cmd_extract, "pilot": cmd_pilot, "submit": cmd_submit,
     "collect": cmd_collect, "status": cmd_status, "write": cmd_write}[args.cmd](args)


if __name__ == "__main__":
    main()
