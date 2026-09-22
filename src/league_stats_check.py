"""How do primatips' league-wide stats predict FT Over 1.5 given HT 0-0 rule-fire?

For each league-stat column (lg_over15, lg_avg_goals, lg_btts, etc.),
bin the HT-0-0 rule-fires by stat value quartile and report hit rate per
quartile. If the stat predicts, the top quartile should hit more than
the bottom.

Also reports a rough point-biserial correlation to give a single number.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from .rule_check import rule_over15_form


TARGET = "outcome_Totals_Over1.5"

# Stats to evaluate. lg_progress is a "season progress" percent, used to
# gauge how reliable the other stats are — early season = noisy.
STATS = [
    "lg_over15", "lg_over25", "lg_over35",
    "lg_avg_goals",
    "lg_home_avg_scored", "lg_away_avg_scored",
    "lg_btts",
    "lg_home_win", "lg_draw", "lg_away_win",
]


def collect(slice_path: Path, min_progress: float | None) -> list[dict]:
    """Return one record per HT-0-0 rule-fire with all league stats and outcome."""
    fires = []
    for line in slice_path.open(encoding="utf-8"):
        r = json.loads(line)
        h_ht = r.get("home_goals_ht"); a_ht = r.get("away_goals_ht")
        if None in (h_ht, a_ht) or h_ht + a_ht != 0:
            continue
        if not rule_over15_form(r):
            continue
        hit = r.get(TARGET)
        if hit is None:
            continue
        if min_progress is not None:
            p = r.get("lg_progress")
            if p is None or p < min_progress:
                continue
        rec = {"hit": bool(hit)}
        for s in STATS + ["lg_progress"]:
            rec[s] = r.get(s)
        fires.append(rec)
    return fires


def quartile_bins(values: list[float], n_bins: int = 4) -> list[float]:
    if len(values) < n_bins:
        return sorted(set(values))
    xs = sorted(values)
    step = len(xs) / n_bins
    return [xs[int(i * step)] for i in range(1, n_bins)]


def bin_report(fires: list[dict], stat: str, n_bins: int = 4) -> None:
    """Report hit rate per quartile of `stat` values."""
    vals = [(f[stat], f["hit"]) for f in fires if f[stat] is not None]
    if len(vals) < n_bins * 2:
        print(f"  {stat}: only {len(vals)} non-null values — skipping")
        return

    just_vals = [v for v, _ in vals]
    edges = quartile_bins(just_vals, n_bins)
    edges = [-math.inf] + edges + [math.inf]

    buckets = [[] for _ in range(n_bins)]
    for v, hit in vals:
        for i in range(n_bins):
            if edges[i] < v <= edges[i + 1]:
                buckets[i].append(hit)
                break

    overall_hit = sum(h for _, h in vals) / len(vals)
    print(f"\n  {stat}   (overall hit rate on non-null subset: {overall_hit:.3f}, "
          f"n={len(vals)})")
    print(f"    {'range':<28} {'n':>4} {'hits':>5} {'rate':>7} {'lift':>7}")
    for i, bucket in enumerate(buckets):
        lo, hi = edges[i], edges[i + 1]
        lo_str = "min" if lo == -math.inf else f"{lo:.2f}"
        hi_str = "max" if hi == math.inf else f"{hi:.2f}"
        rng = f"({lo_str}, {hi_str}]"
        n = len(bucket)
        if n == 0:
            print(f"    {rng:<28} {n:>4}  (no data)")
            continue
        hits = sum(bucket)
        rate = hits / n
        lift = rate - overall_hit
        print(f"    {rng:<28} {n:>4} {hits:>5} {rate:>7.3f} {lift:>+7.3f}")


def point_biserial(fires: list[dict], stat: str) -> tuple[float, int] | tuple[None, int]:
    """Correlation between stat value and hit (binary). Returns (r, n) or (None, n)."""
    pairs = [(f[stat], 1 if f["hit"] else 0) for f in fires if f[stat] is not None]
    n = len(pairs)
    if n < 10:
        return (None, n)
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    denom = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    if denom == 0:
        return (None, n)
    return (num / denom, n)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=Path, required=True)
    ap.add_argument("--min-progress", type=float, default=None,
                    help="Skip rows where league season < X%% complete (e.g. 20)")
    args = ap.parse_args()

    fires = collect(args.slice, args.min_progress)

    print(f"Slice: {args.slice}")
    if args.min_progress is not None:
        print(f"Filter: lg_progress >= {args.min_progress}%")
    print(f"HT 0-0 rule-fires: {len(fires)}")
    hits = sum(1 for f in fires if f["hit"])
    if fires:
        print(f"Overall hit rate: {hits}/{len(fires)} = {hits/len(fires):.3f}")

    # Missingness on league stats
    print("\nLeague-stat missingness among HT 0-0 fires:")
    for s in STATS + ["lg_progress"]:
        miss = sum(1 for f in fires if f[s] is None)
        print(f"  {s:<24} missing: {miss}/{len(fires)}")

    # Correlations, sorted by absolute value
    print("\nPoint-biserial correlations (stat → hit outcome), sorted by |r|:")
    corrs = []
    for s in STATS:
        r, n = point_biserial(fires, s)
        corrs.append((s, r, n))
    corrs.sort(key=lambda x: abs(x[1] or 0), reverse=True)
    for s, r, n in corrs:
        if r is None:
            print(f"  {s:<24}  (n={n}, insufficient data)")
        else:
            marker = ""
            if abs(r) >= 0.15:
                marker = " ← notable"
            print(f"  {s:<24}  r = {r:+.3f}  (n={n}){marker}")

    # Per-stat quartile breakdown
    print("\nQuartile-bin hit rates:")
    for s in STATS:
        bin_report(fires, s, n_bins=4)


if __name__ == "__main__":
    main()
