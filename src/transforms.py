"""Pure per-row transforms: raw fixtures2 row → flat feature dict.

Zero I/O. Zero global state. Every function takes plain Python objects and
returns plain Python objects, so this is trivially testable.

The top-level entry point is `transform_row(row)`.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .rules import resolve_all
from .trends import trend_features


ODDS_KEYS = [
    "home", "draw", "away",
    "_1x", "x2",
    "over15", "under15",
    "over25", "under25",
    "over35", "under35",
    "btts_yes", "btts_no",
]

LEAGUE_STAT_KEYS = [
    "home_win", "draw", "away_win", "progress",
    "avg_goals", "home_avg_scored", "away_avg_scored",
    "home_gsf", "away_gsf",
    "btts", "over15", "over25", "over35",
]

FORM_WINDOWS = (5, 10)

FORM_CONTEXTS = [
    ("home_overall", "home_matches", None),
    ("home_home",    "home_matches", "home"),
    ("away_overall", "away_matches", None),
    ("away_away",    "away_matches", "away"),
]


def _maybe_json(value: Any) -> Any:
    """Decode a JSON string; pass through if already parsed or empty.

    Handles both single-encoded (JSONB via supabase-py) and double-encoded
    (CSV export from Supabase, where the JSON string was itself JSON-escaped).
    After the first decode, if we still have a string, decode once more.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (list, dict)):
        return value
    if not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (json.JSONDecodeError, ValueError):
            return None
    return parsed


def _norm_col(key: str) -> str:
    return key.lstrip("_")


def flatten_odds(odds: dict | None, prefix: str) -> dict:
    out: dict = {}
    for k in ODDS_KEYS:
        col = f"{prefix}_{_norm_col(k)}"
        out[col] = (odds or {}).get(k)
    return out


def flatten_league_stats(ls: dict | None) -> dict:
    out: dict = {}
    for k in LEAGUE_STAT_KEYS:
        out[f"lg_{k}"] = (ls or {}).get(k)
    return out


def flatten_result(result: dict | None) -> dict:
    """Cast to int defensively (source has known string/int inconsistency and
    a lurking parsing bug on double-digit away scores) and derive outcomes.

    Returns nulls with result_valid=False when the result can't be trusted.
    """
    empty = {
        "home_goals": None, "away_goals": None,
        "home_goals_ht": None, "away_goals_ht": None,
        "total_goals": None,
        "ft_outcome": None, "ht_outcome": None,
        "result_valid": False,
    }
    if not result:
        return empty
    try:
        h_fh = int(result["home_goals_fh"])
        h_sh = int(result["home_goals_sh"])
        a_fh = int(result["away_goals_fh"])
        a_sh = int(result["away_goals_sh"])
        if any(v < 0 or v > 20 for v in (h_fh, h_sh, a_fh, a_sh)):
            return empty
        home = h_fh + h_sh
        away = a_fh + a_sh
        ft = "H" if home > away else ("D" if home == away else "A")
        ht = "H" if h_fh > a_fh else ("D" if h_fh == a_fh else "A")
        return {
            "home_goals": home,
            "away_goals": away,
            "home_goals_ht": h_fh,
            "away_goals_ht": a_fh,
            "total_goals": home + away,
            "ft_outcome": ft,
            "ht_outcome": ht,
            "result_valid": True,
        }
    except (KeyError, TypeError, ValueError):
        return empty


def form_features(matches: list[dict], venue_filter: str | None,
                  window: int, prefix: str,
                  fixture_date: str | None = None) -> dict:
    """Aggregate form over the last `window` matches (optionally filtered by venue).

    Also emits `<prefix>_nth_match_days_ago_<window>` — how old the Nth-most-
    recent match is (in days) relative to the fixture. Used to filter out
    stale-form windows (summer break, early season, etc.). Only computed when
    fixture_date is provided AND at least `window` matches are available.
    """
    keys = [
        "n", "win_rate", "draw_rate", "loss_rate",
        "gf_avg", "ga_avg", "goals_avg",
        "btts_rate", "over15_rate", "over25_rate",
        "scored_rate", "clean_sheet_rate",
        "nth_match_days_ago",
    ]
    col = lambda k: f"{prefix}_{k}_{window}"

    filtered = matches
    if venue_filter is not None:
        filtered = [m for m in filtered if m.get("venue") == venue_filter]
    filtered = sorted(filtered, key=lambda m: m["date"], reverse=True)[:window]

    n = len(filtered)
    out = {col(k): None for k in keys}
    out[col("n")] = n

    # Age of the Nth-most-recent match (i.e. the OLDEST of the window used).
    # Filled when we have a full window AND we know the fixture date.
    if fixture_date and n == window:
        try:
            fdate = datetime.strptime(fixture_date, "%Y-%m-%d")
            nth_date = datetime.strptime(filtered[-1]["date"], "%Y-%m-%d")
            out[col("nth_match_days_ago")] = (fdate - nth_date).days
        except (ValueError, TypeError):
            pass

    if n < 3:
        return out

    wins = sum(1 for m in filtered if m["gf"] > m["ga"])
    draws = sum(1 for m in filtered if m["gf"] == m["ga"])
    losses = sum(1 for m in filtered if m["gf"] < m["ga"])
    gf_sum = sum(m["gf"] for m in filtered)
    ga_sum = sum(m["ga"] for m in filtered)
    btts = sum(1 for m in filtered if m["gf"] > 0 and m["ga"] > 0)
    o15 = sum(1 for m in filtered if (m["gf"] + m["ga"]) > 1.5)
    o25 = sum(1 for m in filtered if (m["gf"] + m["ga"]) > 2.5)
    scored = sum(1 for m in filtered if m["gf"] > 0)
    clean = sum(1 for m in filtered if m["ga"] == 0)

    out[col("win_rate")] = round(wins / n, 4)
    out[col("draw_rate")] = round(draws / n, 4)
    out[col("loss_rate")] = round(losses / n, 4)
    out[col("gf_avg")] = round(gf_sum / n, 4)
    out[col("ga_avg")] = round(ga_sum / n, 4)
    out[col("goals_avg")] = round((gf_sum + ga_sum) / n, 4)
    out[col("btts_rate")] = round(btts / n, 4)
    out[col("over15_rate")] = round(o15 / n, 4)
    out[col("over25_rate")] = round(o25 / n, 4)
    out[col("scored_rate")] = round(scored / n, 4)
    out[col("clean_sheet_rate")] = round(clean / n, 4)
    return out


def h2h_features(h2h: list[dict] | None, fixture_date: str,
                 cutoff_years: float = 3.0) -> dict:
    """Weighted H2H aggregates.

    h2h entries have gf/ga already normalized to the current fixture's home
    team perspective (fa_scraper does this in h2h_parser). We linear-decay
    weights from 1.0 (today) to 0.0 (cutoff_years ago), drop older meetings.
    Rates are None when fewer than 2 meetings survive the cutoff.
    """
    empty = {
        "h2h_n_recent": 0,
        "h2h_weight_total": 0.0,
        "h2h_home_win_rate": None, "h2h_draw_rate": None, "h2h_away_win_rate": None,
        "h2h_avg_goals": None, "h2h_avg_gf": None, "h2h_avg_ga": None,
        "h2h_btts_rate": None,
        "h2h_over15_rate": None, "h2h_over25_rate": None, "h2h_over35_rate": None,
    }
    if not h2h:
        return empty

    try:
        fdate = datetime.strptime(fixture_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return empty

    kept: list[tuple[float, dict]] = []
    for m in h2h:
        try:
            mdate = datetime.strptime(m["date"], "%Y-%m-%d")
        except (ValueError, KeyError, TypeError):
            continue
        years_ago = (fdate - mdate).days / 365.25
        if years_ago < 0 or years_ago > cutoff_years:
            continue
        w = max(0.0, 1 - years_ago / cutoff_years)
        kept.append((w, m))

    n = len(kept)
    w_total = sum(w for w, _ in kept)
    out = dict(empty)
    out["h2h_n_recent"] = n
    out["h2h_weight_total"] = round(w_total, 4)
    if n < 2 or w_total == 0:
        return out

    def wavg(fn):
        return sum(w * fn(m) for w, m in kept) / w_total

    out["h2h_home_win_rate"] = round(wavg(lambda m: 1.0 if m["gf"] > m["ga"] else 0.0), 4)
    out["h2h_draw_rate"] = round(wavg(lambda m: 1.0 if m["gf"] == m["ga"] else 0.0), 4)
    out["h2h_away_win_rate"] = round(wavg(lambda m: 1.0 if m["gf"] < m["ga"] else 0.0), 4)
    out["h2h_avg_goals"] = round(wavg(lambda m: m["gf"] + m["ga"]), 4)
    out["h2h_avg_gf"] = round(wavg(lambda m: m["gf"]), 4)
    out["h2h_avg_ga"] = round(wavg(lambda m: m["ga"]), 4)
    out["h2h_btts_rate"] = round(wavg(lambda m: 1.0 if m["gf"] > 0 and m["ga"] > 0 else 0.0), 4)
    out["h2h_over15_rate"] = round(wavg(lambda m: 1.0 if (m["gf"] + m["ga"]) > 1.5 else 0.0), 4)
    out["h2h_over25_rate"] = round(wavg(lambda m: 1.0 if (m["gf"] + m["ga"]) > 2.5 else 0.0), 4)
    out["h2h_over35_rate"] = round(wavg(lambda m: 1.0 if (m["gf"] + m["ga"]) > 3.5 else 0.0), 4)
    return out


def transform_row(row: dict) -> dict:
    """Turn one raw fixtures2 row into a flat feature dict.

    All JSON fields are decoded once. Missing sections yield None-valued
    columns rather than being skipped, so the output schema is stable.
    """
    home_matches = _maybe_json(row.get("home_matches")) or []
    away_matches = _maybe_json(row.get("away_matches")) or []
    odds = _maybe_json(row.get("odds")) or {}
    probs = _maybe_json(row.get("probabilities")) or {}
    h2h = _maybe_json(row.get("h2h")) or []
    result = _maybe_json(row.get("result"))
    league_stats = _maybe_json(row.get("league_stats"))

    league = row.get("league")
    country = row.get("country")

    out: dict = {
        "custom_id": row.get("custom_id"),
        "supabase_id": row.get("id"),
        "home": row.get("home"),
        "away": row.get("away"),
        "league": league.strip() if isinstance(league, str) else league,
        "country": country.strip() if isinstance(country, str) else country,
        "date": row.get("date"),
        "time": row.get("time"),
        "home_pos": row.get("home_pos"),
        "away_pos": row.get("away_pos"),
        "status": row.get("status"),
        "url": row.get("url"),
    }

    out.update(flatten_odds(odds, "odds"))
    out.update(flatten_odds(probs, "prob"))

    out.update(flatten_result(result))

    fixture_date_str = row.get("date")
    for context, source, venue in FORM_CONTEXTS:
        matches = home_matches if source == "home_matches" else away_matches
        for w in FORM_WINDOWS:
            out.update(form_features(matches, venue, w, context,
                                     fixture_date=fixture_date_str))

    out.update(h2h_features(h2h, row.get("date", "")))

    out.update(flatten_league_stats(league_stats))

    for context, source, venue in FORM_CONTEXTS:
        matches = home_matches if source == "home_matches" else away_matches
        out.update(trend_features(matches, venue, context))

    if out["result_valid"]:
        scores = {"gf": out["home_goals"], "ga": out["away_goals"]}
        for name, val in resolve_all(scores).items():
            out[f"outcome_{name}"] = val
    else:
        # Emit the same column set with None so schema is stable across rows.
        from .rules import rules as _rules_dict
        for name in _rules_dict:
            out[f"outcome_{name}"] = None

    return out
