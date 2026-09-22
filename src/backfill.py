"""Walk a date range, scrape focus-league fixtures, save per-day JSONL.

Designed for long, resumable runs:
    - One JSONL file per date under data/backfill/YYYY-MM-DD.jsonl
    - Checkpoint file at data/backfill/checkpoints/completed.txt lists dates done
    - Re-running skips already-completed dates
    - Ctrl+C is safe: the current date might be partial but next-run continues

Usage:
    python3 -m src.backfill --from-date 2024-08-01 --to-date 2024-08-31
    python3 -m src.backfill --from-date 2022-07-01 --to-date 2025-06-30 --delay 1.0
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from .scrape.scraper import scrape_date
from .slice import SLICES


DEFAULT_OUT_DIR = Path("data/backfill")
CHECKPOINT_FILE = DEFAULT_OUT_DIR / "checkpoints" / "completed.txt"


def load_completed() -> set[str]:
    if not CHECKPOINT_FILE.exists():
        return set()
    return set(CHECKPOINT_FILE.read_text().splitlines())


def mark_completed(date: str) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CHECKPOINT_FILE.open("a") as f:
        f.write(f"{date}\n")


def daterange(from_date: str, to_date: str) -> list[str]:
    d0 = datetime.strptime(from_date, "%Y-%m-%d")
    d1 = datetime.strptime(to_date, "%Y-%m-%d")
    if d1 < d0:
        d0, d1 = d1, d0
    days = []
    cur = d0
    while cur <= d1:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return days


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--slice", default="focus",
                    help="Slice name from src.slice.SLICES to filter to")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--delay", type=float, default=1.0,
                    help="Politeness delay between HTTP requests (seconds, jittered ±20%)")
    ap.add_argument("--reverse", action="store_true",
                    help="Walk newest → oldest (default: oldest → newest)")
    ap.add_argument("--max-dates", type=int, default=None,
                    help="Process at most N un-completed dates this run "
                         "(for cron-chunked backfill).")
    ap.add_argument("--max-runtime", type=int, default=None,
                    help="Stop after N seconds regardless of dates remaining "
                         "(safety cap for CI runners).")
    args = ap.parse_args()

    focus = SLICES.get(args.slice)
    if focus is None:
        raise SystemExit(f"unknown slice: {args.slice}. Options: {list(SLICES)}")

    days = daterange(args.from_date, args.to_date)
    if args.reverse:
        days = list(reversed(days))

    completed = load_completed()
    to_do = [d for d in days if d not in completed]
    if args.max_dates is not None:
        to_do = to_do[:args.max_dates]

    print(f"Range: {args.from_date} → {args.to_date}  ({len(days)} days)")
    print(f"Already done: {len(days) - len([d for d in days if d not in completed])}"
          f"   Remaining in range: {len([d for d in days if d not in completed])}"
          f"   This run will process: {len(to_do)}")
    print(f"Focus leagues: {len(focus)}   Delay between requests: {args.delay}s "
          f"(jittered ±20%)")
    if args.max_runtime:
        print(f"Runtime cap: {args.max_runtime}s")
    print(f"Output: {args.out_dir}")
    print()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    grand_total = 0
    t_start = time.time()
    for i, date in enumerate(to_do):
        if args.max_runtime and (time.time() - t_start) >= args.max_runtime:
            print(f"  Runtime cap reached ({args.max_runtime}s); stopping cleanly.")
            break
        t0 = time.time()
        fixtures = scrape_date(date, focus, request_delay=args.delay)
        dt = time.time() - t0

        if fixtures:
            out = args.out_dir / f"{date}.jsonl"
            with out.open("w", encoding="utf-8") as f:
                for fx in fixtures:
                    f.write(json.dumps(fx, ensure_ascii=False))
                    f.write("\n")
            grand_total += len(fixtures)

        mark_completed(date)
        elapsed_total = time.time() - t_start
        est_remaining = (elapsed_total / (i + 1)) * (len(to_do) - i - 1)
        print(f"  [{i+1}/{len(to_do)}] {date}  "
              f"kept={len(fixtures):>3}  time={dt:>5.1f}s  "
              f"total_kept={grand_total}  "
              f"ETA={est_remaining/60:.1f} min")

    print()
    print(f"Done. Total fixtures kept: {grand_total}")


if __name__ == "__main__":
    main()
