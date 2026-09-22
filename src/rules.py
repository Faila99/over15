"""Bet outcome rules — mirrors fa_scraper/src/scraping/rules.py.

Each rule is a predicate over {"gf": home_goals, "ga": away_goals}.
The rule name follows the pattern "<market>_<selection>" so bets stored as
(market, selection) can be resolved with `rules[f"{market}_{selection}"](scores)`.
"""

rules = {}

rules["1X2_Home"] = lambda m: m["gf"] > m["ga"]
rules["1X2_Draw"] = lambda m: m["gf"] == m["ga"]
rules["1X2_Away"] = lambda m: m["ga"] > m["gf"]

rules["DoubleChance_1x"] = lambda m: m["gf"] >= m["ga"]
rules["DoubleChance_x2"] = lambda m: m["ga"] >= m["gf"]
rules["DoubleChance_12"] = lambda m: m["gf"] != m["ga"]

for th in [0.5, 1.5, 2.5, 3.5]:
    rules[f"Totals_Over{th}"] = lambda m, th=th: (m["gf"] + m["ga"]) > th
    rules[f"Totals_Under{th}"] = lambda m, th=th: (m["gf"] + m["ga"]) < th

for th in [0.5, 1.5, 2.5, 3.5]:
    rules[f"HomeTotals_Over{th}"] = lambda m, th=th: m["gf"] > th
    rules[f"HomeTotals_Under{th}"] = lambda m, th=th: m["gf"] < th

for th in [0.5, 1.5, 2.5, 3.5]:
    rules[f"AwayTotals_Over{th}"] = lambda m, th=th: m["ga"] > th
    rules[f"AwayTotals_Under{th}"] = lambda m, th=th: m["ga"] < th

rules["BTTS_Yes"] = lambda m: m["gf"] > 0 and m["ga"] > 0
rules["BTTS_No"] = lambda m: m["gf"] == 0 or m["ga"] == 0

for team in ["Home", "Away"]:
    for h in [1, 2, 3]:
        rules[f"Handicap_{team}-{h}"] = (
            lambda m, team=team, h=h:
                (m["gf"] - m["ga"] - h > 0) if team == "Home"
                else (m["ga"] - m["gf"] - h > 0)
        )
        rules[f"Handicap_{team}+{h}"] = (
            lambda m, team=team, h=h:
                (m["gf"] - m["ga"] + h > 0) if team == "Home"
                else (m["ga"] - m["gf"] + h > 0)
        )


def resolve_all(scores: dict) -> dict:
    """Return {rule_name: bool_or_None} for every rule given a scores dict."""
    out = {}
    for name, fn in rules.items():
        try:
            out[name] = bool(fn(scores))
        except Exception:
            out[name] = None
    return out
