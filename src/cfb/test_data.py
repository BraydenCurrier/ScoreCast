from cfb.models import CollegeFootballGame

TEST_GAMES_CFB = [
    # Mid-game: Close conference matchup (Top 5 battle)
    CollegeFootballGame(
        away="TEX", home="UGA", status="IN_PROGRESS", start_time="7:30 PM",
        away_rank=3, home_rank=2,
        away_score=21, home_score=24,
        away_wins=8, away_losses=1, home_wins=9, home_losses=0,
        quarter=3, clock="4:12",
        possession="TEX", down=3, distance=7,
        yardline_side="TEX", yardline_number=35,
        date="NOV 14", week=11
    ),
    # Early-game: Big Ten clash (The Game)
    CollegeFootballGame(
        away="OSU", home="MICH", status="IN_PROGRESS", start_time="12:00 PM",
        away_rank=2, home_rank=5,
        away_score=7, home_score=0,
        away_wins=10, away_losses=0, home_wins=9, home_losses=1,
        quarter=1, clock="10:00",
        possession="MICH", down=1, distance=10,
        yardline_side="MICH", yardline_number=25,
        date="NOV 28", week=13
    ),
    # Final state: Blowout (One ranked team, one unranked/None)
    CollegeFootballGame(
        away="CLEM", home="FSU", status="FINAL", start_time="3:30 PM",
        away_rank=18, home_rank=25,
        away_score=42, home_score=10,
        away_wins=6, away_losses=4, home_wins=2, home_losses=8,
        quarter=4, clock="0:00",
        possession="", down=0, distance=0,
        yardline_side="", yardline_number=0,
        date="OCT 31", week=9
    ),
    # Pre-game: Awaiting kickoff (Saban-era legacy rivalry)
    CollegeFootballGame(
        away="LSU", home="ALA", status="PRE_GAME", start_time="8:00 PM",
        away_rank=12, home_rank=7,
        away_score=0, home_score=0,
        away_wins=7, away_losses=2, home_wins=8, home_losses=1,
        quarter=0, clock="15:00",
        possession="", down=0, distance=0,
        yardline_side="", yardline_number=0,
        date="NOV 07", week=10
    )
]