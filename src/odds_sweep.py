"""Sweep an odds threshold on top of the rule and report ROI per band.

For each min-odds cutoff, keep only rule-fired bets where the offered Over 1.5
odds are >= cutoff, then compute hit rate, PnL, ROI, and CI.

The 'break-even hit rate' column tells us what hit rate we'd need at that
price to not lose money. If our observed hit rate stays above that,
positive EV — even after acknowledging small samples.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from .rule_check import rule_over15_form, wilson_ci


TARGET = "outcome_Totals_Over1.5"
ODDS_COL = "odds_over15"

DEFAULT_THRESHOLDS = [1.00, 1.15, 1.20, 1.22, 1.24, 1.26, 1.28, 1.30,
                      1.32, 1.35, 1.40, 1.50, 1.60, 1.75, 2.00, 2.25, 2.50]


def sweep(slice_path: Path, rule_fn, target: str, odds_col: str,
          thresholds: list[float]) -> list[dict]:
    fires = []   # (odds, hit_bool) tuples for rule-fired rows
    for line in slice_path.open(encoding="utf-8"):
        r = json.loads(line)
        if not rule_fn(r):
            continue
        odds = r.get(odds_col)
        hit = r.get(target)
        if odds is None or hit is None:
            continue
        fires.append((odds, bool(hit)))

    rows = []
    for th in thresholds:
        subset = [(o, h) for (o, h) in fires if o >= th]
        n = len(subset)
        hits = sum(1 for _, h in subset if h)
        if n == 0:
            rows.append({"min_odds": th, "n": 0})
            continue
        hit_rate = hits / n
        pnl = sum((o - 1) if h else -1 for o, h in subset)
        roi = pnl / n
        ci_lo, ci_hi = wilson_ci(hits, n)
        mean_odds = sum(o for o, _ in subset) / n
        break_even = 1 / mean_odds
        rows.append({
            "min_odds": th,
            "n": n,
            "hits": hits,
            "hit_rate": hit_rate,
            "mean_odds": mean_odds,
            "break_even_hit_rate": break_even,
            "pnl": pnl,
            "roi": roi,
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
        })
    return rows


def print_table(rows: list[dict]) -> None:
    print(f"{'min_odds':>9} {'n':>5} {'hits':>5} {'hit_rate':>9} "
          f"{'mean_odds':>10} {'break_even':>11} {'PnL':>8} {'ROI':>8} {'CI_lo':>7} {'CI_hi':>7}")
    print("-" * 90)
    for r in rows:
        if r["n"] == 0:
            print(f"{r['min_odds']:>9.2f} {0:>5}  (no bets)")
            continue
        margin = r["hit_rate"] - r["break_even_hit_rate"]
        margin_str = f"{margin:+.3f}"
        print(f"{r['min_odds']:>9.2f} {r['n']:>5} {r['hits']:>5} "
              f"{r['hit_rate']:>9.3f} {r['mean_odds']:>10.3f} "
              f"{r['break_even_hit_rate']:>11.3f} {r['pnl']:>+8.2f} "
              f"{r['roi']:>+8.2%} {r['ci_lo']:>7.3f} {r['ci_hi']:>7.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=Path,
                    default=Path("data/clean/matches_top5.jsonl"))
    ap.add_argument("--target", default=TARGET,
                    help="Outcome column, e.g. outcome_Totals_Over2.5")
    ap.add_argument("--odds-col", default=ODDS_COL,
                    help="Odds column matching the target, e.g. odds_over25")
    ap.add_argument("--thresholds", type=float, nargs="*",
                    default=DEFAULT_THRESHOLDS)
    args = ap.parse_args()

    print(f"Target: {args.target}   Odds column: {args.odds_col}")
    print()
    rows = sweep(args.slice, rule_over15_form, args.target, args.odds_col,
                 args.thresholds)
    print_table(rows)


if __name__ == "__main__":
    main()
