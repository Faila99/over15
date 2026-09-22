"""HTML parsers — copied verbatim from fa_scraper/src/scraping/parsers.py.

Same shape / same return values so the downstream cleaner sees identical
input whether the data came from live scraping or backfill.
"""
from __future__ import annotations

import json


def h2h_parser(h2h_table, home_team: str):
    if h2h_table is None:
        return None
    h2h_stats = []
    for match in h2h_table.find("tbody").find_all("tr"):
        date = match.find(class_="date").text.strip()
        home = match.find(class_="hteam").text.strip()
        away = match.find(class_="ateam").text.strip()
        result = match.find(class_="result").text.strip().split("-")
        result = [int(s) for s in result]
        if home.lower() == home_team.lower():
            gf, ga, venue = result[0], result[-1], "home"
        else:
            gf, ga, venue = result[-1], result[0], "away"
        h2h_stats.append({
            "home": home, "away": away, "date": date,
            "gf": gf, "ga": ga, "venue": venue,
        })
    return json.dumps(h2h_stats)


def odds_probs_parser(odds_probs_tables, option: str):
    option_index = 0 if option == "odds" else 1

    def get_data(tables, header_text):
        for table in tables:
            mt = table.find("thead").find("th", class_="odds-type").text.strip()
            if mt != header_text:
                continue
            row = table.find("tbody").find_all("tr")[option_index].find_all("td")[1:]
            cells = [td.text.strip().replace("-", "") for td in row]
            if option == "odds":
                return [float(x) if x else None for x in cells]
            probs = [x.replace("%", "") for x in cells]
            return [int(p) if p else None for p in probs]
        return None

    wdl = get_data(odds_probs_tables, "Standard 1X2")
    dc = get_data(odds_probs_tables, "Double Chance")
    ou15 = get_data(odds_probs_tables, "Over/Under 1.5")
    ou25 = get_data(odds_probs_tables, "Over/Under 2.5")
    ou35 = get_data(odds_probs_tables, "Over/Under 3.5")
    btts = get_data(odds_probs_tables, "Both Teams to Score")

    data = {
        "home":     wdl[0]  if wdl  else None,
        "draw":     wdl[1]  if wdl  else None,
        "away":     wdl[-1] if wdl  else None,
        "_1x":      dc[0]   if dc   else None,
        "x2":       dc[-1]  if dc   else None,
        "over15":   ou15[1] if ou15 else None,
        "under15":  ou15[-1] if ou15 else None,
        "over25":   ou25[1] if ou25 else None,
        "under25":  ou25[-1] if ou25 else None,
        "over35":   ou35[1] if ou35 else None,
        "under35":  ou35[-1] if ou35 else None,
        "btts_yes": btts[1] if btts else None,
        "btts_no":  btts[-1] if btts else None,
    }
    return json.dumps(data)


def team_matches_parser(soup, team_name: str):
    rows = (soup.find("h2", class_="team-title", string="Matches")
                .find_next_sibling("div", class_="gml")
                .find_all(class_="gma"))
    previous = []
    for row in rows:
        home_team = row.find("span", class_="ht2").text.strip()
        away_team = row.find("span", class_="at2").text.strip()
        venue = "home" if home_team.lower() == team_name.lower() else "away"
        date = row.find(class_="date").text.strip()
        try:
            home_odds = float(row.find(class_="ho2").text.strip())
            draw_odds = float(row.find(class_="do").text.strip())
            away_odds = float(row.find(class_="ao2").text.strip())
        except (AttributeError, ValueError):
            home_odds = draw_odds = away_odds = None
        score = row.find("span", class_="res").text.strip().split("-")
        score = [int(s) for s in score]
        if venue == "home":
            gf, ga, team_odds, opp_odds = score[0], score[-1], home_odds, away_odds
        else:
            gf, ga, team_odds, opp_odds = score[-1], score[0], away_odds, home_odds
        previous.append({
            "date": date, "venue": venue, "gf": gf, "ga": ga,
            "team_odds": team_odds, "draw_odds": draw_odds, "opp_odds": opp_odds,
            "home_team": home_team, "away_team": away_team,
        })
    return json.dumps(previous)


def position_parser(rows, team_name: str):
    for row in rows:
        if row.find(class_="team").text.strip().lower() == team_name.lower():
            return int(row.find(class_="position").text.strip())
    return None


STATS_MAP = {
    "Home Win": "home_win", "Draw": "draw", "Away Win": "away_win",
    "Completed Matches": "progress", "Goals per Game": "avg_goals",
    "Home Goals per Game": "home_avg_scored",
    "Away Goals per Game": "away_avg_scored",
    "Home Team Scored in": "home_gsf",
    "Away Team Scored in": "away_gsf",
    "Both Teams to Score": "btts",
    "Over 1.5": "over15", "Over 2.5": "over25", "Over 3.5": "over35",
}


def league_stats_parser(rows):
    stats = {}
    for row in rows:
        data_td = row.find("td", class_="data")
        if data_td is None:
            continue
        label = row.find("td", class_="label").text.strip()
        try:
            val = float(data_td.text.strip().replace("%", ""))
        except ValueError:
            continue
        if label in STATS_MAP:
            stats[STATS_MAP[label]] = val
    return stats


def team_history_from_fixture(soup, team_name: str, fixture_date: str | None = None):
    """Parse a team's 'last 12 games' table AS DISPLAYED ON THE FIXTURE PAGE.

    This is the KEY difference from `team_matches_parser` (which hits the
    separate team page and returns TODAY's recent form, i.e. leakage).
    The fixture-detail page's 'last 12 games' section is anchored to the
    fixture's own date, so it's historically accurate.

    Returns the same JSON shape as `team_matches_parser` so downstream
    consumers don't need to change. Odds fields are set to None (they
    aren't present on this table) — but the rule doesn't use them.
    """
    heading = soup.find(
        "h2", class_="games-title",
        string=lambda s: s and f"{team_name} last 12 games" == s.strip()
    )
    if heading is None:
        # Try a looser fallback in case the team name is displayed slightly
        # differently (e.g. "Man Utd" vs "Manchester Utd").
        heading = soup.find(
            "h2", class_="games-title",
            string=lambda s: s and "last 12 games" in s and "H2H" not in s
                              and _fuzzy_match(team_name, s)
        )
        if heading is None:
            return None

    table = heading.find_next("table")
    if table is None:
        return None

    matches = []
    for row in table.find_all("tr"):
        date_cell = row.find(class_="date")
        home_cell = row.find(class_="hteam")
        away_cell = row.find(class_="ateam")
        result_cell = row.find(class_="result")
        if not (date_cell and home_cell and away_cell and result_cell):
            continue

        date_str = date_cell.text.strip()
        home_team = home_cell.text.strip()
        away_team = away_cell.text.strip()
        score_txt = result_cell.text.strip()

        # Guard: if fixture_date is known, skip anything after (belt-and-braces
        # against potential edge cases where a "future" row sneaks in).
        if fixture_date and date_str >= fixture_date:
            continue

        try:
            parts = [int(x.strip()) for x in score_txt.split("-")]
            home_score, away_score = parts[0], parts[-1]
        except (ValueError, IndexError):
            continue

        if home_team.lower() == team_name.lower():
            venue, gf, ga = "home", home_score, away_score
        elif away_team.lower() == team_name.lower():
            venue, gf, ga = "away", away_score, home_score
        else:
            # Odd row — this team isn't in either slot, skip.
            continue

        matches.append({
            "date": date_str,
            "venue": venue,
            "gf": gf,
            "ga": ga,
            "team_odds": None,   # not present on the fixture-page table
            "draw_odds": None,
            "opp_odds": None,
            "home_team": home_team,
            "away_team": away_team,
        })

    return json.dumps(matches)


def _fuzzy_match(team: str, heading_text: str) -> bool:
    """Very loose team-name match — checks if the shortest recognizable
    piece of the team name shows up in the heading."""
    t = team.lower().split()
    h = heading_text.lower()
    return any(part in h for part in t if len(part) >= 4)


def result_parser(soup):
    """Parse the FT (and HT via the extended-result string) for a finished fixture.

    Returns dict compatible with fa_scraper's `result` field:
        {home_goals_fh, home_goals_sh, away_goals_fh, away_goals_sh}
    or None if the game isn't finished / result can't be parsed.
    """
    ext = soup.find(class_="game-extended-result")
    if ext is None:
        return None
    text = ext.text.strip().replace("(", "").replace(")", "")
    parts = [p.strip() for p in text.split(",")]
    if len(parts) < 2:
        return None
    try:
        fh = [int(x) for x in parts[0].split("-")]
        sh = [int(x) for x in parts[-1].split("-")]
    except ValueError:
        return None
    return {
        "home_goals_fh": fh[0],
        "home_goals_sh": sh[0],
        "away_goals_fh": fh[-1],
        "away_goals_sh": sh[-1],
    }
