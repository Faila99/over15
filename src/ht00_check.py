"""HT 0-0 → FT Over 1.5 analysis on rule-fired fixtures.

For a given slice, apply the current rule, filter to HT 0-0 games, and
report the empirical hit rate for FT Over 1.5 with a Wilson CI + a
break-even table over realistic in-play odds bands.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from .rule_check import rule_over15_form, wilson_ci


TARGET = "outcome_Totals_Over1.5"


def analyze(slice_path: Path) -> dict:
    all_stats = {"n": 0, "ht00": 0, "ht00_o15": 0}
    fire_stats = {"n": 0, "ht00": 0, "ht00_o15": 0}
    prematch_o15_odds = []
    fire_all_o15_odds = []

    for line in slice_path.open(encoding="utf-8"):
        r = json.loads(line)
        h_ht = r.get("home_goals_ht")
        a_ht = r.get("away_goals_ht")
        if None in (h_ht, a_ht):
            continue

        all_stats["n"] += 1
        if h_ht + a_ht == 0:
            all_stats["ht00"] += 1
            if r.get(TARGET):
                all_stats["ht00_o15"] += 1

        if not rule_over15_form(r):
            continue
        fire_stats["n"] += 1
        o = r.get("odds_over15")
        if o is not None:
            fire_all_o15_odds.append(o)
        if h_ht + a_ht == 0:
            fire_stats["ht00"] += 1
            if o is not None:
                prematch_o15_odds.append(o)
            if r.get(TARGET):
                fire_stats["ht00_o15"] += 1

    def rate(hits, n):
        return hits / n if n else None

    fire_ht00_rate = rate(fire_stats["ht00_o15"], fire_stats["ht00"])
    all_ht00_rate = rate(all_stats["ht00_o15"], all_stats["ht00"])
    ci = wilson_ci(fire_stats["ht00_o15"], fire_stats["ht00"])

    return {
        "slice": str(slice_path),
        "all_stats": all_stats,
        "fire_stats": fire_stats,
        "fire_ht00_rate": fire_ht00_rate,
        "all_ht00_rate": all_ht00_rate,
        "ci_lo": ci[0],
        "ci_hi": ci[1],
        "prematch_odds_mean": statistics.mean(prematch_o15_odds) if prematch_o15_odds else None,
        "prematch_odds_median": statistics.median(prematch_o15_odds) if prematch_o15_odds else None,
    }


def print_report(r: dict) -> None:
    a, f = r["all_stats"], r["fire_stats"]
    print(f"Slice: {r['slice']}")
    print()
    print(f"{'':32}{'total':>7}{'HT 0-0':>10}{'→ FT O1.5':>13}")
    print("-" * 65)
    print(f"{'ALL games':<32}{a['n']:>7}"
          f"{a['ht00']:>7} ({a['ht00']/a['n']:.1%})"
          f"{a['ht00_o15']:>7} = {r['all_ht00_rate']:.3f}" if a['n'] else "")
    if f["n"]:
        fire_ht_pct = f["ht00"] / f["n"]
        print(f"{'RULE-FIRED (goal-heavy)':<32}{f['n']:>7}"
              f"{f['ht00']:>7} ({fire_ht_pct:.1%})"
              f"{f['ht00_o15']:>7} = {r['fire_ht00_rate']:.3f}")
    print()

    if f["ht00"] == 0:
        print("No HT 0-0 rule-fires — nothing to score.")
        return

    lift = (r["fire_ht00_rate"] or 0) - (r["all_ht00_rate"] or 0)
    print(f"Lift over general population: {lift:+.3f}")
    print(f"95% Wilson CI on rule-fired hit rate: [{r['ci_lo']:.3f}, {r['ci_hi']:.3f}]")
    print(f"Fair odds needed: {1/r['fire_ht00_rate']:.2f}")
    if r["prematch_odds_median"] is not None:
        print(f"Pre-match Over 1.5 odds for these fires  →  "
              f"mean {r['prematch_odds_mean']:.3f}  median {r['prematch_odds_median']:.3f}")

    print()
    print("Break-even ROI at various in-play odds (assuming observed hit rate holds):")
    print(f"{'in-play odds':>14}{'ROI':>10}")
    for o in [1.60, 1.80, 2.00, 2.20, 2.40, 2.60, 2.80, 3.00]:
        roi = r["fire_ht00_rate"] * o - 1
        marker = " ← positive" if roi > 0 else ""
        print(f"{o:>14.2f}{roi:>+10.2%}{marker}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=Path, required=True,
                    help="Path to a matches_<slice>.jsonl file")
    args = ap.parse_args()
    print_report(analyze(args.slice))


if __name__ == "__main__":
    main()
