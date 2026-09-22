"""Filter the clean dataset to a named slice (competition set).

Consumes data/clean/matches.jsonl (produced by src.clean), writes a subset
plus a "know your data" summary: per-league counts, date range, and base
rates for the pre-resolved bet outcomes so we can eyeball the market
before designing any rule.

Usage:
    python3 -m src.slice --slice top5
    python3 -m src.slice --slice top10_european
    python3 -m src.slice --slice all             # no filter, just re-summarize
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


# (country, league) tuples — post-strip, matching what src.clean produces.
SLICES: dict[str, set[tuple[str, str]]] = {
    "top5": {
        ("England", "Premier League"),
        ("Spain",   "La Liga"),
        ("Italy",   "Serie A"),
        ("Germany", "Bundesliga"),
        ("France",  "Ligue 1"),
    },
    "top10_european": {
        ("England", "Premier League"), ("England", "Championship"),
        ("Spain",   "La Liga"),        ("Spain",   "La Liga 2"),
        ("Italy",   "Serie A"),        ("Italy",   "Serie B"),
        ("Germany", "Bundesliga"),     ("Germany", "2. Bundesliga"),
        ("France",  "Ligue 1"),        ("France",  "Ligue 2"),
    },
    # Top 20 by data volume, excluding third-tier grouped competitions.
    "top20_european": {
        # top-5 top divisions
        ("England", "Premier League"), ("Spain", "La Liga"),
        ("Germany", "Bundesliga"),     ("Italy", "Serie A"),
        ("France",  "Ligue 1"),
        # top-5 second divisions
        ("England", "Championship"),   ("Spain", "La Liga 2"),
        ("Germany", "2. Bundesliga"),  ("Italy", "Serie B"),
        ("France",  "Ligue 2"),
        # English tiers 3/4
        ("England", "League One"),     ("England", "League Two"),
        # Third-tier top-5
        ("Germany", "3. Liga"),
        # Other major top divisions
        ("Portugal",    "Primeira Liga"),
        ("Netherlands", "Eredivisie"),  ("Netherlands", "Eerste Divisie"),
        ("Turkiye",     "Super Lig"),   ("Turkiye",     "TFF First League"),
        ("Poland",      "Ekstraklasa"),
        ("Russia",      "First League"),
    },
    "top10_american": {
        ("Argentina",   "Primera Nacional"),
        ("Argentina",   "Liga Profesional"),
        ("Brazil",      "Serie A"),
        ("Brazil",      "Serie B"),
        ("USA",         "MLS"),
        ("Colombia",    "Primera A"),
        ("Peru",        "Primera"),
        ("Mexico",      "Liga MX"),
        ("El Salvador", "Primera"),
        ("Uruguay",     "Primera"),
    },
    # Leagues where the HT 0-0 → FT Over 1.5 rule shows the clearest signal
    # in the per-league breakdown (hit rate ≥ 55% with n ≥ 15), plus MLS.
    # Selection is on-the-same-data — treat as high-conviction watchlist,
    # not a proven out-of-sample edge.
    "focus": {
        ("Spain",       "La Liga"),          # strong
        ("Netherlands", "Eredivisie"),       # strong
        ("England",     "Premier League"),   # strong
        ("Spain",       "La Liga 2"),        # strong
        ("Netherlands", "Eerste Divisie"),   # solid
        ("England",     "Championship"),     # solid
        ("USA",         "MLS"),              # solid (Americas)
    },
}

BASE_RATE_MARKETS = [
    "1X2_Home", "1X2_Draw", "1X2_Away",
    "DoubleChance_1x", "DoubleChance_x2",
    "Totals_Over1.5", "Totals_Over2.5", "Totals_Over3.5",
    "BTTS_Yes", "BTTS_No",
]


def load_and_filter(src: Path, keep: set[tuple[str, str]] | None):
    for line in src.open(encoding="utf-8"):
        r = json.loads(line)
        if keep is not None and (r.get("country"), r.get("league")) not in keep:
            continue
        yield r


def summarize(rows: list[dict], label: str) -> None:
    if not rows:
        print(f"\n=== {label}: 0 rows ===")
        return

    per_comp: Counter = Counter()
    dates = []
    for r in rows:
        per_comp[(r.get("country"), r.get("league"))] += 1
        d = r.get("date")
        if d:
            dates.append(d)

    dates.sort()
    print(f"\n=== {label}: {len(rows)} rows ===")
    print(f"Date range: {dates[0]} → {dates[-1]}")
    print("Per-competition breakdown:")
    for (c, l), n in per_comp.most_common():
        print(f"  {n:>5}  {c} — {l}")

    print("\nMarket base rates (over the whole slice):")
    for name in BASE_RATE_MARKETS:
        col = f"outcome_{name}"
        hits = sum(1 for r in rows if r.get(col) is True)
        rate = hits / len(rows)
        print(f"  {name:<20} {hits:>5} / {len(rows):>5}  =  {rate:.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=Path("data/clean/matches.jsonl"))
    ap.add_argument("--slice", "-s", choices=list(SLICES.keys()) + ["all"],
                    default="top5")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output JSONL (default: data/clean/matches_<slice>.jsonl)")
    args = ap.parse_args()

    keep = SLICES.get(args.slice)   # None for 'all'
    out = args.out or Path(f"data/clean/matches_{args.slice}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Reading {args.src}  →  slice={args.slice}  →  {out}")

    rows: list[dict] = []
    with out.open("w", encoding="utf-8") as f:
        for r in load_and_filter(args.src, keep):
            f.write(json.dumps(r, ensure_ascii=False))
            f.write("\n")
            rows.append(r)

    print(f"Wrote {len(rows)} rows → {out} ({out.stat().st_size / 1e6:.1f} MB)")
    summarize(rows, args.slice)


if __name__ == "__main__":
    main()
