"""Entry point: raw fixtures2 rows → flat, feature-rich dataset.

Two input modes:
    --from-csv PATH   Read a Supabase CSV export (stdlib only, no deps).
    (default)         Query the fixtures2 table live via supabase-py.

Two output modes:
    --to-jsonl PATH   Line-delimited JSON (stdlib only).
    --to-parquet PATH Parquet via pandas/pyarrow (requires those installed).

Usage:
    # No deps needed:
    python3 -m src.clean --from-csv data/raw/fixtures2.csv \
                         --to-jsonl data/clean/matches.jsonl

    # With deps:
    python3 -m src.clean --to-parquet data/clean/matches.parquet
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterable

from .derive import derive_stream
from .transforms import transform_row


TABLE = "fixtures2"
PAGE_SIZE = 1000


# ---------- Loaders ----------

def load_jsonl(path: Path) -> Iterable[dict]:
    """Stream rows from a JSONL file (backfill output)."""
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_csv(path: Path) -> Iterable[dict]:
    """Stream rows from a Supabase CSV export."""
    # csv default field size cap is 128KB — h2h/matches arrays can exceed that.
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # empty strings from CSV → None for JSON-typed columns so
            # _maybe_json short-circuits cleanly.
            for k in ("home_matches", "away_matches", "odds", "probabilities",
                      "h2h", "result", "league_stats"):
                if row.get(k) == "":
                    row[k] = None
            # Cast numeric fields where useful.
            for k in ("home_pos", "away_pos", "id"):
                v = row.get(k)
                if v not in (None, ""):
                    try:
                        row[k] = int(v)
                    except ValueError:
                        pass
            yield row


def load_supabase(limit: int | None = None) -> list[dict]:
    """Paginate through fixtures2 via supabase-py."""
    try:
        from dotenv import load_dotenv
        from supabase import create_client
    except ImportError as e:
        print(f"ERROR: Supabase mode needs supabase-py + python-dotenv installed ({e})",
              file=sys.stderr)
        print("Either `pip install -r requirements.txt` or use --from-csv.", file=sys.stderr)
        sys.exit(1)

    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set in .env", file=sys.stderr)
        sys.exit(1)
    sb = create_client(url, key)

    rows: list[dict] = []
    start = 0
    while True:
        end = start + PAGE_SIZE - 1
        if limit is not None:
            end = min(end, start + (limit - len(rows)) - 1)
        t0 = time.time()
        resp = (
            sb.table(TABLE)
            .select("*")
            .order("id", desc=False)
            .range(start, end)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        print(f"  fetched {len(batch):>5} rows ({start}-{start + len(batch) - 1}) "
              f"in {time.time() - t0:.1f}s — total {len(rows)}")
        if len(batch) < PAGE_SIZE:
            break
        if limit is not None and len(rows) >= limit:
            break
        start += PAGE_SIZE
    return rows


# ---------- Transform ----------

def transform_stream(rows: Iterable[dict]) -> Iterable[dict]:
    errors = 0
    seen = 0
    for i, row in enumerate(rows):
        seen += 1
        try:
            yield transform_row(row)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  transform failed on row "
                      f"{row.get('custom_id') or row.get('id') or i}: {e}",
                      file=sys.stderr)
    if errors:
        print(f"  {errors} of {seen} rows failed transform (skipped)", file=sys.stderr)


def filter_and_dedupe(records: Iterable[dict]) -> tuple[list[dict], Counter]:
    """Keep only closed fixtures with a valid result. Drop duplicates.

    Primary dedup key: `custom_id` (canonical — home, away, country, league, date).
    Secondary: (home, away, date) — safety net in case custom_id got mangled
    by whitespace/casing at scrape time.
    """
    stats: Counter = Counter()
    seen_cid: set[str] = set()
    seen_composite: set[tuple] = set()
    kept: list[dict] = []

    for r in records:
        stats["seen"] += 1
        if r.get("status") != "closed":
            stats["dropped_not_closed"] += 1
            continue
        if not r.get("result_valid"):
            stats["dropped_invalid_result"] += 1
            continue
        cid = r.get("custom_id")
        if cid and cid in seen_cid:
            stats["dropped_dupe_custom_id"] += 1
            continue
        composite = (r.get("home"), r.get("away"), r.get("date"))
        if all(composite) and composite in seen_composite:
            stats["dropped_dupe_composite"] += 1
            continue
        if cid:
            seen_cid.add(cid)
        if all(composite):
            seen_composite.add(composite)
        kept.append(r)

    stats["kept"] = len(kept)
    return kept, stats


# ---------- Writers ----------

def write_jsonl(records: Iterable[dict], out: Path) -> tuple[int, list[str]]:
    """Write JSONL, return (row_count, all_columns_seen)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    columns: set[str] = set()
    n = 0
    with out.open("w", encoding="utf-8") as f:
        for rec in records:
            columns.update(rec.keys())
            f.write(json.dumps(rec, ensure_ascii=False))
            f.write("\n")
            n += 1
            if n % 5000 == 0:
                print(f"  wrote {n} rows...")
    return n, sorted(columns)


def write_parquet(records: Iterable[dict], out: Path) -> tuple[int, list[str]]:
    try:
        import pandas as pd
    except ImportError:
        print("ERROR: parquet output needs pandas + pyarrow installed.", file=sys.stderr)
        sys.exit(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame.from_records(list(records))
    df.to_parquet(out, index=False)
    return len(df), list(df.columns)


# ---------- CLI ----------

def _summarize(jsonl_path: Path) -> None:
    """Eyeball summary — all rows here are already status=closed + result_valid."""
    total = 0
    leagues: Counter = Counter()
    date_min = None
    date_max = None
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            total += 1
            leagues[(rec.get("country"), rec.get("league"))] += 1
            d = rec.get("date")
            if d:
                date_min = d if date_min is None or d < date_min else date_min
                date_max = d if date_max is None or d > date_max else date_max
    print(f"\nTotal rows: {total}")
    print(f"Date range: {date_min} → {date_max}")
    print(f"Distinct (country, league) pairs: {len(leagues)}")
    print("Top 15 competitions by row count:")
    for (c, l), n in leagues.most_common(15):
        print(f"  {n:>5}  {c} — {l}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-csv", type=Path, help="Path to Supabase CSV export")
    ap.add_argument("--from-jsonl", type=Path, action="append", default=[],
                    help="Extra JSONL source (backfill dumps). May repeat.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap rows (works for both csv and supabase modes)")
    dst = ap.add_mutually_exclusive_group()
    dst.add_argument("--to-jsonl", type=Path, default=Path("data/clean/matches.jsonl"))
    dst.add_argument("--to-parquet", type=Path, help="Parquet output (needs pandas)")
    ap.add_argument("--derive", action="store_true",
                    help="Rebuild home_matches/away_matches/h2h from the pool. "
                         "Required when combining backfill (which has no team histories) "
                         "with live data.")
    ap.add_argument("--summary", action="store_true", default=True,
                    help="Print a summary of output after writing (default on)")
    args = ap.parse_args()

    # ---- load (combine all sources into one materialized pool if deriving,
    # else stream for memory friendliness)
    raw_rows: list[dict] = []

    if args.from_csv:
        print(f"Reading CSV: {args.from_csv}")
        for r in load_csv(args.from_csv):
            raw_rows.append(r)
            if args.limit is not None and len(raw_rows) >= args.limit:
                break

    for p in args.from_jsonl:
        print(f"Reading JSONL: {p}")
        for r in load_jsonl(p):
            raw_rows.append(r)

    if not args.from_csv and not args.from_jsonl:
        print("Fetching from Supabase...")
        raw_rows = load_supabase(limit=args.limit)

    print(f"Loaded {len(raw_rows)} raw rows")

    # ---- derive (optional): rebuild team histories from the pool
    if args.derive:
        print("Deriving home_matches / away_matches / h2h from the pool...")
        raw_rows, stats = derive_stream(raw_rows)
        print(f"  teams in pool:          {stats['teams_in_pool']}")
        print(f"  median history length:  {stats['median_history_len']}")
        print(f"  rows with home history: {stats['rows_with_home_history']}")
        print(f"  rows with away history: {stats['rows_with_away_history']}")
        print(f"  rows with h2h:          {stats['rows_with_h2h']}")

    rows_iter: Iterable[dict] = iter(raw_rows)

    # ---- transform, then filter + dedupe (materialize because we need stats)
    print("Transforming...")
    transformed = list(transform_stream(rows_iter))
    print(f"  transformed {len(transformed)} rows")

    print("Filtering (status=closed + result_valid) and deduping...")
    kept, stats = filter_and_dedupe(transformed)
    print(f"  seen                {stats['seen']:>7}")
    print(f"  dropped: not closed {stats['dropped_not_closed']:>7}")
    print(f"  dropped: bad result {stats['dropped_invalid_result']:>7}")
    print(f"  dropped: dupe cid   {stats['dropped_dupe_custom_id']:>7}")
    print(f"  dropped: dupe hAD   {stats['dropped_dupe_composite']:>7}   (home, away, date)")
    print(f"  kept                {stats['kept']:>7}")

    # ---- write
    if args.to_parquet:
        n, cols = write_parquet(iter(kept), args.to_parquet)
        out = args.to_parquet
    else:
        n, cols = write_jsonl(iter(kept), args.to_jsonl)
        out = args.to_jsonl

    size_mb = out.stat().st_size / 1e6
    print(f"\nWrote {n} rows × {len(cols)} cols → {out} ({size_mb:.1f} MB)")

    if args.summary and args.to_jsonl and out == args.to_jsonl:
        _summarize(out)


if __name__ == "__main__":
    main()
