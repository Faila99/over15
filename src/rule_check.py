"""Apply one rule to a slice, report hit rate vs base rate.

For now the rule is hardcoded — once we've validated a few candidates we'll
generalize to a rule spec. Keeps the first iterations honest and readable.

Usage:
    python3 -m src.rule_check
    python3 -m src.rule_check --slice data/clean/matches_top5.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


TARGET = "outcome_Totals_Over1.5"


MAX_5TH_MATCH_DAYS = 60


def rule_over15_form(row: dict) -> bool:
    """Candidate rule for Over 1.5:
    1. Both teams' avg scored (last 5) >= 1.0
    2. H2H over-1.5 history >= 0.80
    3. Both teams scored in >= 4 of last 5 (rate >= 0.80)
    4. NEW: both teams' 5th-most-recent match is <= 60 days old
       (drops fires where form data is stale from summer/winter break or
       season just started — see diagnostic in this session showing the
       ">60 days" bucket collapsed from 64.5% to 16.7% hit rate)
    """
    home_gf = row.get("home_overall_gf_avg_5")
    away_gf = row.get("away_overall_gf_avg_5")
    h2h = row.get("h2h_over15_rate")
    home_sc = row.get("home_overall_scored_rate_5")
    away_sc = row.get("away_overall_scored_rate_5")
    home_age = row.get("home_overall_nth_match_days_ago_5")
    away_age = row.get("away_overall_nth_match_days_ago_5")

    if None in (home_gf, away_gf, h2h, home_sc, away_sc, home_age, away_age):
        return False
    return (
        home_gf >= 1.0
        and away_gf >= 1.0
        and h2h >= 0.80
        and home_sc >= 0.80
        and away_sc >= 0.80
        and home_age <= MAX_5TH_MATCH_DAYS
        and away_age <= MAX_5TH_MATCH_DAYS
    )


def wilson_ci(hits: int, n: int, z: float = 1.96) -> tuple[float, float] | tuple[None, None]:
    if n == 0:
        return (None, None)
    p = hits / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (center - half, center + half)


def evaluate(slice_path: Path, rule_fn, target_col: str) -> dict:
    total = 0
    base_hits = 0
    fired = 0
    hits = 0
    filtered_out = {"missing_data": 0, "rule_false": 0}

    for line in slice_path.open(encoding="utf-8"):
        r = json.loads(line)
        total += 1
        if r.get(target_col) is True:
            base_hits += 1

        # Track WHY rows didn't fire — separates "features unavailable"
        # from "rule genuinely rejected the row"
        try:
            fired_flag = rule_fn(r)
        except Exception:
            filtered_out["missing_data"] += 1
            continue

        if fired_flag:
            fired += 1
            if r.get(target_col) is True:
                hits += 1
        else:
            # Determine reason for not firing (heuristic)
            needed = ["home_overall_gf_avg_5", "away_overall_gf_avg_5",
                      "h2h_over15_rate", "home_overall_scored_rate_5",
                      "away_overall_scored_rate_5"]
            if any(r.get(k) is None for k in needed):
                filtered_out["missing_data"] += 1
            else:
                filtered_out["rule_false"] += 1

    base_rate = base_hits / total if total else 0.0
    hit_rate = hits / fired if fired else 0.0
    lift = hit_rate - base_rate
    ci_lo, ci_hi = wilson_ci(hits, fired)

    return {
        "slice": str(slice_path),
        "target": target_col,
        "total": total,
        "base_hits": base_hits,
        "base_rate": base_rate,
        "fired": fired,
        "hits": hits,
        "hit_rate": hit_rate,
        "lift": lift,
        "ci_low": ci_lo,
        "ci_high": ci_hi,
        "filtered_out": filtered_out,
    }


def print_report(r: dict) -> None:
    print(f"Slice:    {r['slice']}")
    print(f"Target:   {r['target']}")
    print()
    print(f"Total matches:      {r['total']}")
    print(f"Base hit count:     {r['base_hits']}  ({r['base_rate']:.1%})")
    print()
    print(f"Rule fired:         {r['fired']} / {r['total']}  ({r['fired']/r['total']:.1%})")
    print(f"  filtered — missing feature data: {r['filtered_out']['missing_data']}")
    print(f"  filtered — rule condition false: {r['filtered_out']['rule_false']}")
    print()
    if r["fired"] > 0:
        print(f"Rule hit rate:      {r['hits']} / {r['fired']}  =  {r['hit_rate']:.3f}")
        print(f"Base rate:                              {r['base_rate']:.3f}")
        print(f"Lift over base:                         {r['lift']:+.3f}")
        print(f"95% Wilson CI:      [{r['ci_low']:.3f}, {r['ci_high']:.3f}]")
        print(f"Fair odds implied:  {1 / r['hit_rate']:.3f}")
    else:
        print("Rule fired zero times — sample too thin or conditions too strict.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=Path,
                    default=Path("data/clean/matches_top5.jsonl"))
    ap.add_argument("--target", default=TARGET)
    args = ap.parse_args()

    result = evaluate(args.slice, rule_over15_form, args.target)
    print_report(result)


if __name__ == "__main__":
    main()
