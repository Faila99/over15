"""Sanity checks on the sample fixture: 07 Vestur vs B36 Torshavn, 2025-08-30.

Ground truth (verified by hand from the raw row):
    * final: 0-1 (07V lost); half-time 0-0
    * league / country arrive with whitespace on primatips; must be stripped
    * 12 H2H entries; 2 are older than 3y from fixture date → 10 kept
    * H2H (from 07V home-team perspective): 0 wins, 4 draws, 6 losses among kept
    * 07V last-5 (any venue): W L L L L
    * 07V last-5 at home: 2025-08-23 W, 2025-08-02 L, 2025-05-25 W, 2025-05-16 W, 2025-05-09 L
"""
import json
from pathlib import Path

import pytest

from src.transforms import transform_row


@pytest.fixture(scope="module")
def sample_row():
    path = Path(__file__).parent / "sample.json"
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def out(sample_row):
    return transform_row(sample_row)


def test_meta_normalized(out):
    assert out["custom_id"] == "07 Vestur-B36 Torshavn_ Faroe Islands_Premier _2025-08-30"
    assert out["home"] == "07 Vestur"
    assert out["away"] == "B36 Torshavn"
    assert out["league"] == "Premier"
    assert out["country"] == "Faroe Islands"
    assert out["date"] == "2025-08-30"
    assert out["home_pos"] == 10
    assert out["away_pos"] == 5
    assert out["status"] == "closed"


def test_odds_flattened(out):
    assert out["odds_home"] == 3.5
    assert out["odds_draw"] == 3.7
    assert out["odds_away"] == 1.77
    assert out["odds_1x"] == 1.93
    assert out["odds_x2"] == 1.26
    assert out["odds_over25"] == 1.47
    assert out["odds_btts_yes"] == 1.47


def test_probabilities_flattened(out):
    assert out["prob_home"] == 29
    assert out["prob_away"] == 65
    assert out["prob_over25"] == 71


def test_result_parsed_despite_string_away_goals(out):
    assert out["result_valid"] is True
    assert out["home_goals"] == 0
    assert out["away_goals"] == 1
    assert out["home_goals_ht"] == 0
    assert out["away_goals_ht"] == 0
    assert out["total_goals"] == 1
    assert out["ft_outcome"] == "A"
    assert out["ht_outcome"] == "D"


def test_bet_outcomes_pre_resolved(out):
    assert out["outcome_1X2_Away"] is True
    assert out["outcome_1X2_Home"] is False
    assert out["outcome_1X2_Draw"] is False
    assert out["outcome_DoubleChance_x2"] is True
    assert out["outcome_DoubleChance_1x"] is False
    assert out["outcome_Totals_Over0.5"] is True
    assert out["outcome_Totals_Under1.5"] is True
    assert out["outcome_Totals_Over1.5"] is False
    assert out["outcome_BTTS_No"] is True
    assert out["outcome_BTTS_Yes"] is False
    assert out["outcome_Handicap_Away-1"] is False   # away won by exactly 1, needs > 1
    assert out["outcome_Handicap_Away+1"] is True


def test_h2h_recency_cutoff_and_weighting(out):
    # 2022-06-26 and 2022-05-08 are > 3 years before 2025-08-30 → excluded.
    assert out["h2h_n_recent"] == 10
    # All 10 kept meetings are draws or losses from 07V perspective → 0 wins.
    assert out["h2h_home_win_rate"] == 0.0
    # 4 draws + 6 losses / 10 → but weighted; recent (2025) matches dominate.
    # Recent 4 are all losses → draw_rate should be < 0.4, loss_rate > 0.6.
    assert out["h2h_draw_rate"] is not None
    assert out["h2h_away_win_rate"] is not None
    assert out["h2h_draw_rate"] + out["h2h_away_win_rate"] == pytest.approx(1.0, abs=1e-3)
    assert out["h2h_away_win_rate"] > 0.6
    # weight_total should be strictly between 0 and 10 (weights are all < 1)
    assert 0 < out["h2h_weight_total"] < 10


def test_home_form_overall_5(out):
    # last 5 for 07V: 2025-08-23 W, 2025-08-17 L, 2025-08-10 L, 2025-08-02 L, 2025-07-05 L
    assert out["home_overall_n_5"] == 5
    assert out["home_overall_win_rate_5"] == 0.2
    assert out["home_overall_loss_rate_5"] == 0.8
    assert out["home_overall_scored_rate_5"] == 0.4   # 3-0 W and 3-4 L → scored in 2 of 5
    assert out["home_overall_clean_sheet_rate_5"] == 0.2  # only the 3-0 win


def test_home_form_at_home_5(out):
    # 07V home-only last 5: 2025-08-23 W(3-0), 2025-08-02 L(1-2), 2025-06-22 L(1-2),
    #                       2025-06-14 L(0-4), 2025-05-25 W(3-1)
    assert out["home_home_n_5"] == 5
    assert out["home_home_win_rate_5"] == 0.4
    assert out["home_home_scored_rate_5"] == 0.8   # 4 of 5 scored


def test_away_form_on_road_5(out):
    # B36 away-only last 5: 2025-08-10 L(2-4), 2025-06-22 L(1-2), 2025-05-31 W(3-2),
    #                      2025-05-16 L(1-2), 2025-04-26 W(3-1)
    assert out["away_away_n_5"] == 5
    assert out["away_away_win_rate_5"] == 0.4


def test_league_stats_absent_is_null(out):
    assert out["lg_home_win"] is None
    assert out["lg_over25"] is None


def test_trend_columns_present(out):
    # Trend engine should have run for all 4 contexts × 14 markets → 112 columns.
    trend_cols = [k for k in out if k.endswith("_streak_n") or k.endswith("_streak_rate")]
    assert len(trend_cols) == 4 * 14 * 2


def test_schema_stable_when_result_missing():
    row = {
        "custom_id": "X_2025-01-01",
        "home": "A", "away": "B", "league": "X", "country": "Y",
        "date": "2025-01-01", "status": "open",
        "home_matches": None, "away_matches": None,
        "odds": None, "probabilities": None,
        "h2h": None, "result": None, "league_stats": None,
    }
    out = transform_row(row)
    assert out["result_valid"] is False
    assert out["home_goals"] is None
    # All outcome_ columns should exist and be None.
    outcomes = {k: v for k, v in out.items() if k.startswith("outcome_")}
    assert len(outcomes) > 30
    assert all(v is None for v in outcomes.values())
