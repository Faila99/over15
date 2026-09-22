"""Scrape one primatips date, returning fixture dicts for focus leagues.

Adapted from fa_scraper's scraper.py but tuned for backfill:
    - Doesn't skip finished fixtures; instead extracts their result inline.
    - Applies a URL-slug pre-filter to skip detail fetches for non-focus fixtures.
    - Returns Python dicts (not upserted to any DB) so the caller controls storage.
"""
from __future__ import annotations

import random
import time
from datetime import datetime

from bs4 import BeautifulSoup
from unidecode import unidecode

from .parsers import (
    h2h_parser, odds_probs_parser,
    position_parser, league_stats_parser, result_parser,
)
from .utils import safe_request


BASE_URL = "https://primatips.com"


# Map (country, league) → URL slug marker. The marker must appear in the fixture
# href for us to bother fetching the detail page. Each is bracketed with hyphens
# to make substring matching safe (e.g. so `-primera-division-spain-` doesn't
# collide with `-primera-division-rfef-group-1-spain-`).
#
# NOTE: primatips uses the *native/traditional* league name in slugs, not the
# marketing name. So "La Liga" → primera-division, MLS → major-league-soccer.
FOCUS_URL_MARKERS: dict[tuple[str, str], str] = {
    ("England",     "Premier League"):   "-premier-league-england-",
    ("England",     "Championship"):     "-championship-england-",
    ("Spain",       "La Liga"):          "-primera-division-spain-",
    ("Spain",       "La Liga 2"):        "-segunda-division-spain-",
    ("Netherlands", "Eredivisie"):       "-eredivisie-netherlands-",
    ("Netherlands", "Eerste Divisie"):   "-eerste-divisie-netherlands-",
    ("USA",         "MLS"):              "-major-league-soccer-usa-",
}


def _normalize(s: str) -> str:
    return unidecode(s).lower().strip()


def _jittered_sleep(base: float) -> None:
    """Politeness delay with ±20% jitter, so traffic doesn't look robotic."""
    if base <= 0:
        return
    time.sleep(base * random.uniform(0.8, 1.2))


def scrape_date(date: str, focus_leagues: set[tuple[str, str]],
                request_delay: float = 1.0) -> list[dict]:
    """Return list of fixture dicts for `date` matching any (country, league) in focus."""
    url = f"{BASE_URL}/tips/{date}"
    resp = safe_request(url)
    if resp is None:
        print(f"  [{date}] no response for listing page")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    games_container = soup.find(id="games")
    if games_container is None:
        return []

    fixture_cards = games_container.find_all("a", class_="game")
    normalized_focus = {(_normalize(c), _normalize(l)) for c, l in focus_leagues}

    # URL-slug pre-filter: skip detail-page fetches for fixtures whose href
    # doesn't contain any of our focus-league markers. Saves ~15x on requests
    # per day (from ~370 detail fetches to ~25).
    active_markers = [FOCUS_URL_MARKERS[k] for k in focus_leagues
                      if k in FOCUS_URL_MARKERS]

    results: list[dict] = []
    for card in fixture_cards:
        href = card.get("href")
        if not href:
            continue

        # Pre-filter — only fetch detail if the URL slug matches a focus league.
        if active_markers and not any(m in href for m in active_markers):
            continue

        _jittered_sleep(request_delay)
        detail_resp = safe_request(f"{BASE_URL}{href}")
        if detail_resp is None:
            continue
        detail = BeautifulSoup(detail_resp.text, "html.parser")

        # league + country — must pass focus filter or we discard
        league_node = detail.find("h1", class_="game-league")
        if league_node is None:
            continue
        try:
            country_span = league_node.find("span")
            country = country_span.text.strip()
            for span in league_node.find_all("span"):
                span.extract()
            league = league_node.text.strip(" -")
        except AttributeError:
            continue

        if (_normalize(country), _normalize(league)) not in normalized_focus:
            continue

        # standings table (required for pre-match positions)
        tables = detail.find_all("table", class_="standing")
        if not tables or len(tables) > 1:
            continue
        standing = tables[0]

        # teams
        try:
            team_flags = detail.find(class_="team-flags")
            home = team_flags.find(class_="team-flag-left").find("h1").text.strip()
            away = team_flags.find(class_="team-flag-right").find("h1").text.strip()
        except AttributeError:
            continue

        # date + kickoff time
        fixture_date, kickoff = None, None
        try:
            game_time_div = detail.find("div", class_="game-time")
            parts = game_time_div.contents
            date_str = parts[0].strip().split(", ")[1]
            fixture_date = datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
            kickoff = parts[2].text.strip()
        except (AttributeError, IndexError, ValueError):
            pass

        # positions
        home_pos = away_pos = None
        try:
            trs = standing.find("tbody").find_all("tr")
            home_pos = position_parser(trs, home)
            away_pos = position_parser(trs, away)
        except AttributeError:
            pass

        fixture = {
            "custom_id": f"{home}-{away}_{country}_{league}_{fixture_date}",
            "status": "closed",   # backfill only stores finished fixtures — set below if not
            "home": home,
            "away": away,
            "league": league,
            "country": country,
            "date": fixture_date,
            "time": kickoff,
            "url": href,
            "home_pos": home_pos,
            "away_pos": away_pos,
        }

        # H2H
        try:
            h2h_title = detail.select_one(
                "h2.games-title:-soup-contains('H2H last')"
            )
            no_data = (h2h_title.find_next_sibling("div", class_="games-stat-no-data")
                       if h2h_title else None)
            if h2h_title and not no_data:
                h2h_table = h2h_title.find_next_sibling("table")
                fixture["h2h"] = h2h_parser(h2h_table, home) if h2h_table else None
            else:
                fixture["h2h"] = None
        except AttributeError:
            fixture["h2h"] = None

        # odds + probabilities
        try:
            wrapper = detail.select_one(
                'div.games-stat-wrapper:has(h2:-soup-contains("Coefficients and Probabilities"))'
            )
            tables_odds = wrapper.find_all(class_="odds") if wrapper else []
            fixture["odds"] = odds_probs_parser(tables_odds, "odds") if tables_odds else None
            fixture["probabilities"] = (odds_probs_parser(tables_odds, "probs")
                                        if tables_odds else None)
        except AttributeError:
            fixture["odds"] = None
            fixture["probabilities"] = None

        # team histories intentionally NOT scraped from the fixture page:
        #   - fixture-detail "last 12 games" includes friendlies + cups
        #     (inconsistent with live team-page scrape which is league-only)
        #   - team-page scrape is leaked (shows today's data for historical fixtures)
        # Instead, form features will be DERIVED post-scrape from the accumulated
        # results pool (backfill + live), guaranteeing league-only consistency.
        fixture["home_matches"] = None
        fixture["away_matches"] = None

        # league_stats intentionally skipped: leaked on historical pages
        # (progress=100% always) AND per prior correlation analysis, added no
        # signal to the rule anyway.
        fixture["league_stats"] = None

        # result — key backfill add: for finished games we parse the score directly.
        result = result_parser(detail)
        if result is None:
            # not finished; skip since backfill only wants closed games
            continue
        # sanity check: the FA scraper has a known bug where away goals are
        # sometimes stored as strings — here they arrive as ints from parsers.
        fixture["result"] = result

        # Serialize league_stats/h2h/etc to JSON strings so downstream sees the
        # same shape as CSV export of Supabase JSONB columns (double-encoded
        # in transforms._maybe_json).
        import json as _json
        for k in ("odds", "probabilities", "h2h",
                  "home_matches", "away_matches", "result", "league_stats"):
            v = fixture.get(k)
            if v is None:
                continue
            if not isinstance(v, str):
                fixture[k] = _json.dumps(v)

        results.append(fixture)

    return results
