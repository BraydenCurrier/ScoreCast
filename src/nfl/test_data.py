from nfl.models import FootballGame

TEST_GAMES_NFL = [
    # -------------------------------------------------------------
    # CASE 1: HOME TEAM DRIVING - DEEP IN OWN TERRITORY
    # Direction check: Home (DET) drives Right-to-Left. 
    # Ball is on their own 22, meaning it should map near the far-right side.
    # Football nose must point LEFT, body trailing to the right.
    # -------------------------------------------------------------
    FootballGame(
        away="GB", home="DET", status="LIVE", start_time="",
        away_score=21, home_score=17, away_wins=10, away_losses=4, home_wins=11, home_losses=3,
        quarter=4, clock="12:23", possession="DET", down=3, distance=22,
        yardline_side="DET", yardline_number=22
    ),

    # -------------------------------------------------------------
    # CASE 2: AWAY TEAM DRIVING - SHORT YARDAGE, MIDFIELD
    # Direction check: Away (PIT) drives Left-to-Right.
    # Ball is on their own 18. Maps near the far-left goal line.
    # Football nose must point RIGHT, body trailing to the left.
    # -------------------------------------------------------------
    FootballGame(
        away="PIT", home="BAL", status="LIVE", start_time="",
        away_score=42, home_score=13, away_wins=9, away_losses=5, home_wins=11, home_losses=3,
        quarter=3, clock="12:12", possession="PIT", down=2, distance=4,
        yardline_side="PIT", yardline_number=18
    ),

    # -------------------------------------------------------------
    # CASE 3: HOME TEAM DRIVING - GOAL TO GO (CRITICAL BOUNDARY TEST)
    # Direction check: Home (KC) drives Right-to-Left. 
    # Opponent's 2-yard line means they are 2 yards away from scoring on the LEFT.
    # This tests if your football nose stays inside the field or clips the goal line.
    # -------------------------------------------------------------
    FootballGame(
        away="LV", home="KC", status="LIVE", start_time="",
        away_score=14, home_score=24, away_wins=5, away_losses=9, home_wins=12, home_losses=2,
        quarter=4, clock="2:15", possession="KC", down=1, distance=2,
        yardline_side="LV", yardline_number=2
    ),

    # -------------------------------------------------------------
    # CASE 4: AWAY TEAM DRIVING - RED ZONE STALL (CRITICAL BOUNDARY TEST)
    # Direction check: Away (SF) drives Left-to-Right.
    # Opponent's 5-yard line means they are 5 yards away from scoring on the RIGHT.
    # Verifies if the `fx = scrimmage_x - 4` calculation keeps the ball visible or clips.
    # -------------------------------------------------------------
    FootballGame(
        away="SF", home="SEA", status="LIVE", start_time="",
        away_score=28, home_score=27, away_wins=10, away_losses=4, home_wins=8, home_losses=6,
        quarter=4, clock="0:45", possession="SF", down=4, distance=5,
        yardline_side="SEA", yardline_number=5
    ),

    # -------------------------------------------------------------
    # CASE 5: DEAD CENTER 50-YARD LINE TEST
    # Tests exact mid-field balance. No matter who is driving, `scrimmage_x`
    # should lock exactly onto your 50-yard line visual pixel column.
    # -------------------------------------------------------------
    FootballGame(
        away="PHI", home="DAL", status="LIVE", start_time="",
        away_score=7, home_score=7, away_wins=9, away_losses=5, home_wins=10, home_losses=4,
        quarter=1, clock="6:30", possession="DAL", down=1, distance=10,
        yardline_side="", yardline_number=50
    ),

    # -------------------------------------------------------------
    # CASE 6: THE "BACK TO THE WALL" SAFETY RISK
    # Away team (MIA) has possession on their OWN 1-yard line (Left side).
    # Tests if the trailing body of the right-facing ball clips backward 
    # into the left endzone layer.
    # -------------------------------------------------------------
    FootballGame(
        away="MIA", home="NE", status="LIVE", start_time="",
        away_score=3, home_score=10, away_wins=6, away_losses=8, home_wins=4, home_losses=10,
        quarter=2, clock="14:05", possession="MIA", down=3, distance=14,
        yardline_side="MIA", yardline_number=1
    )
]