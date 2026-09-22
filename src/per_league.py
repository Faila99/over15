"""Per-league breakdown of the HT 0-0 → FT Over 1.5 strategy.

For each (country, league) in the slice, report how many rule-fires reached
HT 0-0, how often those hit FT Over 1.5, and the Wilson CI. Sort by hit rate.

Flags:
    ★  n >= 15 (interpretable sample)
    ⚠  n <  15 (too thin — treat as directional only)
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .rule_check import rule_over15_form, wilson_ci


TARGET = "outcome_Totals_Over1.5"
MIN_SAMPLE_INTERPRETABLE = 15
BREAK_EVEN_ODDS_BANDS = [2.00, 2.20, 2.40, 2.60]


def analyze(slice_path: Path) -> list[dict]:
    # bucket: (country, league) -> stats dict
    buckets: dict[tuple, dict] = defaultdict(
        lambda: {"total": 0, "fires": 0, "ht00": 0, "ht00_hit": 0,
                 "sum_prematch_odds": 0.0, "n_odds": 0}
    )
    for line in slice_path.open(encoding="utf-8"):
        r = json.loads(line)
        key = (r.get("country"), r.get("league"))
        b = buckets[key]
        b["total"] += 1

        h_ht = r.get("home_goals_ht")
        a_ht = r.get("away_goals_ht")
        if None in (h_ht, a_ht):
            continue

        if not rule_over15_form(r):
            continue
        b["fires"] += 1
        if h_ht + a_ht == 0:
            b["ht00"] += 1
            if r.get(TARGET):
                b["ht00_hit"] += 1
            o = r.get("odds_over15")
            if o is not None:
                b["sum_prematch_odds"] += o
                b["n_odds"] += 1

    rows = []
    for (country, league), b in buckets.items():
        n = b["ht00"]
        hits = b["ht00_hit"]
        rate = hits / n if n else None
        ci_lo, ci_hi = wilson_ci(hits, n)
        rows.append({
            "country": country,
            "league": league,
            "total": b["total"],
            "fires": b["fires"],
            "ht00": n,
            "hits": hits,
            "hit_rate": rate,
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
            "mean_prematch_odds": (b["sum_prematch_odds"] / b["n_odds"])
                                   if b["n_odds"] else None,
        })
    return rows


def print_table(rows: list[dict], sort_by: str = "hit_rate") -> None:
    # Filter out leagues with 0 fires (still show 0-fire in a footnote)
    scored = [r for r in rows if r["ht00"] > 0]
    zero_ht00 = [r for r in rows if r["ht00"] == 0]

    if sort_by == "hit_rate":
        scored.sort(key=lambda r: (r["hit_rate"] or 0, r["ht00"]), reverse=True)
    elif sort_by == "n":
        scored.sort(key=lambda r: r["ht00"], reverse=True)

    hdr = f"{'':2} {'country':<14} {'league':<25} {'total':>6} {'fires':>6} " \
          f"{'HT00':>5} {'hits':>5} {'rate':>7} {'CI_lo':>7} {'CI_hi':>7} " \
          + " ".join(f"@{o:>4.2f}" for o in BREAK_EVEN_ODDS_BANDS)
    print(hdr)
    print("-" * len(hdr))

    for r in scored:
        flag = "★" if r["ht00"] >= MIN_SAMPLE_INTERPRETABLE else "⚠"
        rate = r["hit_rate"]
        rois = []
        for o in BREAK_EVEN_ODDS_BANDS:
            roi = rate * o - 1
            rois.append(f"{roi:>+5.1%}")
        print(f"{flag:2} {r['country'] or '':<14} {(r['league'] or '')[:25]:<25} "
              f"{r['total']:>6} {r['fires']:>6} {r['ht00']:>5} {r['hits']:>5} "
              f"{rate:>7.3f} {r['ci_lo']:>7.3f} {r['ci_hi']:>7.3f} "
              + " ".join(rois))

    if zero_ht00:
        print()
        print(f"({len(zero_ht00)} leagues with zero HT 0-0 rule-fires: "
              + ", ".join(f"{r['country']}/{r['league']}" for r in zero_ht00[:5])
              + (", ..." if len(zero_ht00) > 5 else "") + ")")

    n_meaningful = sum(1 for r in scored if r["ht00"] >= MIN_SAMPLE_INTERPRETABLE)
    print()
    print(f"Legend: ★ = n >= {MIN_SAMPLE_INTERPRETABLE} (interpretable);  "
          f"⚠ = n < {MIN_SAMPLE_INTERPRETABLE} (directional only)")
    print(f"Interpretable leagues: {n_meaningful} / {len(scored)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=Path, required=True)
    ap.add_argument("--sort", choices=["hit_rate", "n"], default="hit_rate")
    args = ap.parse_args()

    rows = analyze(args.slice)
    print(f"Per-league breakdown: HT 0-0 rule-fires → FT Over 1.5")
    print(f"Slice: {args.slice}")
    print()
    print_table(rows, sort_by=args.sort)


if __name__ == "__main__":
    main()
