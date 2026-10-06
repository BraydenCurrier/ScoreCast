from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from bets.analytics import MIN_LABEL_SAMPLE, build_labels, summarize
from bets.catalog import STATUS_LOST, STATUS_PUSH, STATUS_VOID, STATUS_WON, positions_for_market
from bets.odds import (
    combine_american_odds,
    payout_from_american,
    profit_from_american,
    result_profit,
)
from bets.probability import estimate_hit_chance
from bets.tracker import _leg_estimate
from bets.settlement import (
    grade_game_market,
    grade_over_under,
    grade_player_market,
    settle_parlay,
)
from bets import store


class PositionFilterTests(unittest.TestCase):
    def test_passing_yards_are_quarterbacks(self):
        self.assertIn("QB", positions_for_market("nfl", "pass_yds"))
        self.assertNotIn("WR", positions_for_market("nfl", "pass_yds"))

    def test_mlb_pitcher_vs_hitter(self):
        self.assertIn("P", positions_for_market("mlb", "pitcher_k"))
        self.assertIn("RF", positions_for_market("mlb", "home_runs"))
        self.assertNotIn("P", positions_for_market("mlb", "home_runs"))

    def test_nba_unfiltered(self):
        self.assertIsNone(positions_for_market("nba", "points"))


class OddsTests(unittest.TestCase):
    def test_plus_odds(self):
        self.assertEqual(profit_from_american(100, 150), 150)
        self.assertEqual(payout_from_american(100, 150), 250)

    def test_minus_odds(self):
        self.assertEqual(profit_from_american(100, -200), 50)
        self.assertEqual(payout_from_american(100, -200), 150)

    def test_percent_to_american(self):
        from bets.odds import american_to_implied_percent, implied_percent_to_american, parse_american_odds
        self.assertEqual(implied_percent_to_american(50), 100)
        self.assertEqual(parse_american_odds("57.45%"), -135)
        self.assertEqual(parse_american_odds("57.45"), -135)
        self.assertEqual(parse_american_odds("-135"), -135)
        self.assertEqual(parse_american_odds("+150"), 150)
        self.assertAlmostEqual(american_to_implied_percent(-135), 57.45, places=1)

    def test_parlay_combo(self):
        self.assertEqual(combine_american_odds([100, 100]), 300)

    def test_result_profit_skips_missing(self):
        self.assertIsNone(result_profit("won", None, 110))
        self.assertIsNone(result_profit("won", 50, None))
        self.assertEqual(result_profit("lost", 50, -110), -50)
        self.assertEqual(result_profit("push", 50, -110), 0)


class SettlementTests(unittest.TestCase):
    def test_over_win_loss_push(self):
        self.assertEqual(grade_over_under(75, 74.5, "over", final=True), STATUS_WON)
        self.assertEqual(grade_over_under(74, 74.5, "over", final=True), STATUS_LOST)
        self.assertEqual(grade_over_under(74, 74, "over", final=True), STATUS_PUSH)
        self.assertIsNone(grade_over_under(40, 74.5, "over", final=False))
        self.assertEqual(grade_over_under(80, 74.5, "over", final=False), STATUS_WON)

    def test_under_does_not_lose_early_unless_busted(self):
        self.assertIsNone(grade_over_under(40, 74.5, "under", final=False))
        self.assertEqual(grade_over_under(80, 74.5, "under", final=False), STATUS_LOST)
        self.assertEqual(grade_over_under(70, 74.5, "under", final=True), STATUS_WON)

    def test_missing_final_player_stat_is_review(self):
        self.assertEqual(
            grade_player_market(
                market="pass_yds",
                direction="over",
                line=274.5,
                value=None,
                final=True,
            ),
            "review",
        )

    def test_spread_and_total(self):
        self.assertEqual(
            grade_game_market(
                market="spread",
                direction="spread_away",
                line=3.5,
                away_score=20,
                home_score=17,
                final=True,
            ),
            STATUS_WON,
        )
        self.assertEqual(
            grade_game_market(
                market="total",
                direction="total_over",
                line=47.5,
                away_score=24,
                home_score=20,
                final=True,
            ),
            STATUS_LOST,
        )
        self.assertIsNone(
            grade_game_market(
                market="moneyline",
                direction="ml_home",
                line=None,
                away_score=10,
                home_score=14,
                final=False,
            )
        )

    def test_parlay_push_void(self):
        self.assertEqual(settle_parlay(["won", "lost", "pending"]), STATUS_LOST)
        self.assertEqual(settle_parlay(["won", "push"]), STATUS_WON)
        self.assertEqual(settle_parlay(["won", "void", "won"]), STATUS_WON)
        self.assertEqual(settle_parlay(["push", "push"]), STATUS_PUSH)
        self.assertEqual(settle_parlay(["void", "void"]), STATUS_VOID)
        self.assertEqual(settle_parlay(["won", "live"]), "live")
        self.assertEqual(settle_parlay(["won", "review"]), "review")


class AnalyticsTests(unittest.TestCase):
    def test_skips_bets_without_money(self):
        bets = [
            {
                "kind": "single",
                "status": STATUS_WON,
                "stake": None,
                "odds_american": 110,
                "archived": 0,
                "legs": [{"status": STATUS_WON, "player_name": "A", "market": "pass_yds", "league": "nfl", "direction": "over", "team": "DAL"}],
            },
            {
                "kind": "single",
                "status": STATUS_WON,
                "stake": 100,
                "odds_american": 100,
                "archived": 0,
                "settled_at": "2026-01-01",
                "legs": [{"status": STATUS_WON, "player_name": "A", "market": "pass_yds", "league": "nfl", "direction": "over", "team": "DAL"}],
            },
        ]
        stats = summarize(bets)
        self.assertEqual(stats["money_sample"], 1)
        self.assertEqual(stats["net"], 100)

    def test_labels_need_sample(self):
        bets = []
        for index in range(MIN_LABEL_SAMPLE - 1):
            bets.append({
                "kind": "single",
                "status": STATUS_LOST,
                "archived": 0,
                "stake": 10,
                "odds_american": -110,
                "settled_at": f"2026-01-0{index+1}",
                "legs": [{
                    "status": STATUS_LOST,
                    "player_name": "Josh Allen",
                    "market": "pass_yds",
                    "league": "nfl",
                    "direction": "over",
                    "team": "BUF",
                }],
            })
        labels = build_labels(bets)
        self.assertFalse(any(item["code"] == "nogo" for item in labels))


class ProbabilityTests(unittest.TestCase):
    def test_already_over(self):
        estimate = estimate_hit_chance(
            current=90,
            line=89.5,
            direction="over",
            remaining_fraction=0.4,
        )
        self.assertGreaterEqual(estimate["chance"], 99)

    def test_on_pace_after_first_quarter(self):
        estimate = estimate_hit_chance(
            current=25,
            line=100,
            direction="over",
            remaining_fraction=0.75,
        )
        self.assertIsNotNone(estimate["chance"])
        self.assertAlmostEqual(estimate["chance"], 50.0, delta=3)

    def test_too_early(self):
        estimate = estimate_hit_chance(
            current=10,
            line=89.5,
            direction="over",
            remaining_fraction=0.97,
        )
        self.assertIsNone(estimate["chance"])

    def test_player_props_only(self):
        spread = _leg_estimate({
            "market": "spread",
            "direction": "spread_home",
            "line": -3.5,
            "current_value": 14,
            "remaining_fraction": 0.5,
            "status": "live",
        })
        prop = _leg_estimate({
            "market": "rush_yds",
            "direction": "over",
            "line": 100,
            "current_value": 25,
            "remaining_fraction": 0.75,
            "status": "live",
        })
        self.assertIsNone(spread["chance"])
        self.assertIsNotNone(prop["chance"])


class StoreAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        store._initialized = False
        store.DB_PATH = Path(self.tmpdir.name) / "bets.sqlite"
        store.init_store()

    def tearDown(self):
        self.tmpdir.cleanup()
        store._initialized = False

    def test_user_isolation_and_manual_override(self):
        payload = {
            "kind": "single",
            "stake": "10",
            "odds_american": "-110",
            "legs": [{
                "league": "nfl",
                "market": "pass_yds",
                "direction": "over",
                "line": "274.5",
                "event_id": "1",
                "event_label": "DAL @ PHI",
                "player_id": "12",
                "player_name": "Dak Prescott",
                "team": "DAL",
                "home_team": "PHI",
                "away_team": "DAL",
            }],
        }
        first = store.create_bet("user-a", payload)
        store.create_bet("user-b", payload)
        self.assertIsNone(store.get_bet(first["id"], "user-b"))
        self.assertIsNotNone(store.get_bet(first["id"], "user-a"))
        store.update_bet_fields(first["id"], "user-a", {
            "status": STATUS_WON,
            "manual_result": 1,
        })
        loaded = store.get_bet(first["id"], "user-a")
        self.assertEqual(loaded["status"], STATUS_WON)
        self.assertEqual(loaded["manual_result"], 1)
        self.assertFalse(store.delete_bet(first["id"], "user-b"))
        self.assertTrue(store.delete_bet(first["id"], "user-a"))


if __name__ == "__main__":
    unittest.main()
