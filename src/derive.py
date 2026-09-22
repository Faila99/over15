"""Rebuild home_matches / away_matches / h2h from the accumulated results pool.

Motivation: primatips' data-sources are inconsistent for our needs:
    - team-page "Matches" section (live) is league-only  ✓
    - fixture-page "last 12 games" section (backfill) includes cups/friendlies  ✗
    - team-page on historical dates shows TODAY's form (leaked)  ✗

By deriving from raw results in our own pool, we guarantee:
    - LEAGUE-ONLY (only fixtures scraped for focus leagues make it in the pool)
    - CONSISTENT across live + backfill data
    - HISTORICALLY ACCURATE (only fixtures with date < target-date are used)
    - TRANSPARENT (we know exactly what's in every team's history)

Usage: called from clean.py as a pipeline stage between load and transform.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Iterable


def _parse_result(r: dict) -> tuple[int, int] | None:
    """Extract (home_goals, away_goals) as ints from a raw row's result field."""
    result = r.get("result")
    if not result:
        return None
    if isinstance(result, str):
        try:
            result = json.loads(result)
            if isinstance(result, str):   # double-encoded
                result = json.loads(result)
        except (json.JSONDecodeError, ValueError):
            return None
    try:
        home = int(result["home_goals_fh"]) + int(result["home_goals_sh"])
        away = int(result["away_goals_fh"]) + int(result["away_goals_sh"])
    except (KeyError, ValueError, TypeError):
        return None
    if any(v < 0 or v > 20 for v in (home, away)):
        return None
    return home, away


def build_pool_index(rows: Iterable[dict]) -> dict[str, list[dict]]:
    """Build {team: [match_entry, ...]} from the pool, sorted by date descending.

    Each match_entry uses the same shape as fa_scraper's team_matches_parser
    output so downstream transforms don't need to change.
    """
    by_team: dict[str, list[dict]] = defaultdict(list)

    for r in rows:
        parsed = _parse_result(r)
        if parsed is None:
            continue
        home_g, away_g = parsed
        home = r.get("home")
        away = r.get("away")
        date = r.get("date")
        if not (home and away and date):
            continue

        by_team[home].append({
            "date": date, "venue": "home",
            "gf": home_g, "ga": away_g,
            "team_odds": None, "draw_odds": None, "opp_odds": None,
            "home_team": home, "away_team": away,
        })
        by_team[away].append({
            "date": date, "venue": "away",
            "gf": away_g, "ga": home_g,
            "team_odds": None, "draw_odds": None, "opp_odds": None,
            "home_team": home, "away_team": away,
        })

    for team in by_team:
        by_team[team].sort(key=lambda m: m["date"], reverse=True)

    return by_team


def derive_row(row: dict, by_team: dict[str, list[dict]],
               history_cap: int = 20) -> dict:
    """Return a copy of row with home_matches / away_matches / h2h rebuilt
    from the pool (dates strictly before the fixture)."""
    r = dict(row)
    home = r.get("home")
    away = r.get("away")
    fx_date = r.get("date")

    if not (home and away and fx_date):
        return r

    home_hist = by_team.get(home, [])
    away_hist = by_team.get(away, [])

    home_matches = [m for m in home_hist if m["date"] < fx_date][:history_cap]
    away_matches = [m for m in away_hist if m["date"] < fx_date][:history_cap]

    r["home_matches"] = json.dumps(home_matches) if home_matches else None
    r["away_matches"] = json.dumps(away_matches) if away_matches else None

    # H2H — take home-team's history, filter to entries against `away`.
    # Convert to the format expected by transforms.h2h_features:
    #   {home, away, date, gf, ga, venue} — gf/ga from current home team perspective
    h2h = []
    for m in home_hist:
        if m["date"] >= fx_date:
            continue
        # m is from home team's perspective. opponent is derived from home_team/away_team.
        opp = m["away_team"] if m["home_team"] == home else m["home_team"]
        if opp == away:
            h2h.append({
                "home": m["home_team"],
                "away": m["away_team"],
                "date": m["date"],
                "gf": m["gf"],   # already from home team's (current fixture) perspective
                "ga": m["ga"],
                "venue": m["venue"],
            })
    h2h.sort(key=lambda m: m["date"], reverse=True)
    if h2h:
        r["h2h"] = json.dumps(h2h[:history_cap])

    return r


def derive_stream(rows: list[dict], history_cap: int = 20) -> tuple[list[dict], dict]:
    """Build the pool once, then derive per-row. Returns (rows, stats)."""
    by_team = build_pool_index(rows)
    stats = {
        "teams_in_pool": len(by_team),
        "median_history_len": 0,
        "rows_with_home_history": 0,
        "rows_with_away_history": 0,
        "rows_with_h2h": 0,
    }
    if by_team:
        lens = sorted(len(v) for v in by_team.values())
        stats["median_history_len"] = lens[len(lens) // 2]

    out = []
    for r in rows:
        derived = derive_row(r, by_team, history_cap=history_cap)
        if derived.get("home_matches"):
            stats["rows_with_home_history"] += 1
        if derived.get("away_matches"):
            stats["rows_with_away_history"] += 1
        if derived.get("h2h"):
            stats["rows_with_h2h"] += 1
        out.append(derived)

    return out, stats
