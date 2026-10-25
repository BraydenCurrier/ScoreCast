import unittest

from common.football_play import (
    challenge_details,
    latest_challenge,
    play_under_review,
)


SAINTS = (
    "T.Shough pass incomplete short left to C.Olave (A.Samuel)."
    "New Orleans challenged the incomplete pass ruling, and the play was REVERSED."
    "T.Shough pass short left to C.Olave pushed ob at NO 40 for 14 yards (A.Samuel)."
)
REVIEW_REF = {
    "type": "CHALLENGE",
    "upheld": False,
    "team": {
        "$ref": "http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2026/teams/18"
    },
}


def _payload(plays):
    return {
        "header": {
            "competitions": [
                {
                    "competitors": [
                        {"team": {"id": "18", "abbreviation": "NO"}},
                        {"team": {"id": "23", "abbreviation": "PIT"}},
                    ]
                }
            ]
        },
        "drives": {
            "previous": [{"plays": plays}],
        },
    }


def _play(sequence, text="", review=None):
    play = {"sequenceNumber": sequence, "text": text}
    if review is not None:
        play["review"] = review
    return play


class ChallengeParseTests(unittest.TestCase):
    def test_saints_challenge_names_the_team_and_the_call(self):
        details = challenge_details(SAINTS, REVIEW_REF, {"18": "NO"})
        self.assertEqual(details["challenge_kind"], "challenge")
        self.assertEqual(details["challenge_team"], "NO")
        self.assertEqual(details["challenge_call"], "INC")
        self.assertEqual(details["challenge_result"], "OVERTURNED")

    def test_scoreboard_text_counts_as_a_review(self):
        self.assertTrue(
            play_under_review({}, {"text": SAINTS, "type": {"text": "Pass Reception"}})
        )
        self.assertFalse(
            play_under_review(
                {},
                {"text": "T.Shough pass incomplete short left to C.Olave.", "type": {}},
            )
        )

    def test_booth_review_keeps_the_call(self):
        text = (
            "The Replay Official reviewed the passer was not down by contact ruling, "
            "and the play was REVERSED."
        )
        details = challenge_details(
            text,
            {"type": "OFFICIAL", "upheld": False},
        )
        self.assertEqual(details["challenge_kind"], "review")
        self.assertEqual(details["challenge_team"], "")
        self.assertEqual(details["challenge_call"], "DOWN")
        self.assertEqual(details["challenge_result"], "OVERTURNED")

    def test_recent_challenge_stays_up_and_an_old_one_drops(self):
        challenge = _play(4, SAINTS, REVIEW_REF)
        later = [_play(5, "pass incomplete"), _play(6, "pass incomplete")]
        shown = latest_challenge(_payload([_play(1, "kickoff"), challenge, *later]))
        self.assertEqual(shown["challenge_team"], "NO")
        hidden = latest_challenge(
            _payload([challenge, *later, _play(7, "rush"), _play(8, "punt")])
        )
        self.assertEqual(hidden["challenge_kind"], "")

    def test_upheld_challenge_stands(self):
        text = (
            "Kansas City challenged the pass completion ruling, "
            "and the play was Upheld. The ruling on the field stands."
        )
        details = challenge_details(text, {"type": "CHALLENGE", "upheld": True})
        self.assertEqual(details["challenge_call"], "CATCH")
        self.assertEqual(details["challenge_result"], "STANDS")
