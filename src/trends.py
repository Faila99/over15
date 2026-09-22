"""Trend feature engineering — adapted from fa_scraper/src/analysis/trends.

For each (team, venue-context) × market, find the longest window in
[min_n, max_n] where the boolean series' success rate is ≥ threshold.

Emits two columns per (context, market): `<prefix>_<market>_streak_n` and
`<prefix>_<market>_streak_rate`. If no window qualifies, both are None.
"""
from typing import Iterable

MARKETS = [
    "win", "draw", "loss",
    "o15", "o25",
    "btts",
    "scored_o15", "conceded_o15",
    "minus_1", "minus_2", "minus_3",
    "plus_1", "plus_2", "plus_3",
]


def _build_boolean_series(matches: list[dict]) -> dict[str, list[bool]]:
    """Boolean vectors per market, from the focal team's perspective.

    Assumes each match has integer 'gf' and 'ga' from the focal team's view.
    """
    goal_diff = [m["gf"] - m["ga"] for m in matches]
    return {
        "win": [gd > 0 for gd in goal_diff],
        "draw": [m["gf"] == m["ga"] for m in matches],
        "loss": [gd < 0 for gd in goal_diff],
        "o15": [(m["gf"] + m["ga"]) > 1.5 for m in matches],
        "o25": [(m["gf"] + m["ga"]) > 2.5 for m in matches],
        "btts": [m["gf"] > 0 and m["ga"] > 0 for m in matches],
        "scored_o15": [m["gf"] > 1.5 for m in matches],
        "conceded_o15": [m["ga"] > 1.5 for m in matches],
        "minus_1": [gd > 1 for gd in goal_diff],
        "minus_2": [gd > 2 for gd in goal_diff],
        "minus_3": [gd > 3 for gd in goal_diff],
        "plus_1": [gd > -1 for gd in goal_diff],
        "plus_2": [gd > -2 for gd in goal_diff],
        "plus_3": [gd > -3 for gd in goal_diff],
    }


def _prefix_sum(bools: Iterable[bool]) -> list[int]:
    ps = [0]
    for b in bools:
        ps.append(ps[-1] + (1 if b else 0))
    return ps


def _rate_last_n(prefix: list[int], n: int) -> float | None:
    if len(prefix) - 1 < n:
        return None
    return (prefix[-1] - prefix[-1 - n]) / n


def _best_window(prefix: list[int], threshold: float, min_n: int, max_n: int):
    """Return (n, rate) for the longest n where rate ≥ threshold, or None."""
    best = None
    for n in range(min_n, max_n + 1):
        r = _rate_last_n(prefix, n)
        if r is None or r < threshold:
            continue
        if best is None or n > best[0]:
            best = (n, r)
    return best


def trend_features(
    matches: list[dict],
    venue_filter: str | None,
    prefix: str,
    threshold: float = 0.8,
    min_n: int = 5,
    max_n: int = 15,
) -> dict:
    """Produce a flat dict of trend features for one (team, venue) context.

    Args:
        matches: list of match dicts with 'date', 'venue', 'gf', 'ga' from the
            focal team's perspective.
        venue_filter: None → all matches; 'home' or 'away' → filter to that
            venue only (used for home-at-home and away-on-the-road contexts).
        prefix: column-name prefix (e.g. 'home_overall', 'home_home',
            'away_overall', 'away_away').
        threshold: minimum success rate to qualify as a trend (default 0.8).
        min_n / max_n: window sizes to search over.
    """
    filtered = matches
    if venue_filter is not None:
        filtered = [m for m in filtered if m.get("venue") == venue_filter]
    filtered = sorted(filtered, key=lambda m: m["date"])[-max_n:]

    out: dict = {}
    if len(filtered) < min_n:
        for market in MARKETS:
            out[f"{prefix}_{market}_streak_n"] = None
            out[f"{prefix}_{market}_streak_rate"] = None
        return out

    series = _build_boolean_series(filtered)
    for market, bools in series.items():
        prefix_sums = _prefix_sum(bools)
        best = _best_window(prefix_sums, threshold, min_n, max_n)
        if best is None:
            out[f"{prefix}_{market}_streak_n"] = None
            out[f"{prefix}_{market}_streak_rate"] = None
        else:
            n, rate = best
            out[f"{prefix}_{market}_streak_n"] = n
            out[f"{prefix}_{market}_streak_rate"] = round(rate, 4)
    return out
