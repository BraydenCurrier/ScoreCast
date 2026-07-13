from nfl.models import FootballGame

TEST_GAMES_NFL = [
    FootballGame(
        away="GB", home="DET", status="LIVE", start_time="",
        away_score=21, home_score=17, away_wins=10, away_losses=4, home_wins=11, home_losses=3,
        quarter=4, clock="12:23", possession="DET", down=3, distance=22,
        yardline_side="DET", yardline_number=22
    ),

    FootballGame(
        away="PIT", home="BAL", status="LIVE", start_time="",
        away_score=42, home_score=13, away_wins=9, away_losses=5, home_wins=11, home_losses=3,
        quarter=3, clock="12:12", possession="PIT", down=2, distance=4,
        yardline_side="PIT", yardline_number=18
    ),

    FootballGame(
        away="LV", home="KC", status="LIVE", start_time="",
        away_score=14, home_score=24, away_wins=5, away_losses=9, home_wins=12, home_losses=2,
        quarter=4, clock="2:15", possession="KC", down=1, distance=2,
        yardline_side="LV", yardline_number=2
    ),

    FootballGame(
        away="SF", home="SEA", status="LIVE", start_time="",
        away_score=28, home_score=27, away_wins=10, away_losses=4, home_wins=8, home_losses=6,
        quarter=4, clock="0:45", possession="SF", down=4, distance=5,
        yardline_side="SEA", yardline_number=5
    ),

    FootballGame(
        away="PHI", home="DAL", status="LIVE", start_time="",
        away_score=7, home_score=7, away_wins=9, away_losses=5, home_wins=10, home_losses=4,
        quarter=1, clock="6:30", possession="DAL", down=1, distance=10,
        yardline_side="", yardline_number=50
    ),

    FootballGame(
        away="MIA", home="NE", status="LIVE", start_time="",
        away_score=3, home_score=10, away_wins=6, away_losses=8, home_wins=4, home_losses=10,
        quarter=2, clock="14:05", possession="MIA", down=3, distance=14,
        yardline_side="MIA", yardline_number=1
    )
]