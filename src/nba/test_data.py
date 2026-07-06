from nba.models import BasketballGame


TEST_GAMES_NBA = [

    # Scheduled Today
    BasketballGame(
        away="LAL",
        home="BOS",
        status="SCHEDULED",
        start_time="6:30",
        date="Oct 22",
        away_score=0,
        home_score=0,
        away_wins=0,
        away_losses=0,
        home_wins=0,
        home_losses=0,
    ),

    BasketballGame(
        away="NYK",
        home="MIA",
        status="SCHEDULED",
        start_time="7:00",
        date="Oct 22",
        away_score=0,
        home_score=0,
        away_wins=0,
        away_losses=0,
        home_wins=0,
        home_losses=0,
    ),

    # First Quarter
    BasketballGame(
        away="DEN",
        home="PHX",
        status="Live",
        start_time="",
        date="",
        away_score=18,
        home_score=15,
        away_wins=57,
        away_losses=25,
        home_wins=49,
        home_losses=33,
        quarter=1,
        clock="3:48",
    ),

    # Second Quarter
    BasketballGame(
        away="MIL",
        home="CHI",
        status="Live",
        start_time="",
        date="",
        away_score=46,
        home_score=39,
        away_wins=55,
        away_losses=27,
        home_wins=39,
        home_losses=43,
        quarter=2,
        clock="5:17",
    ),

    # Halftime
    BasketballGame(
        away="DAL",
        home="GS",
        status="Halftime",
        start_time="",
        date="",
        away_score=61,
        home_score=58,
        away_wins=52,
        away_losses=30,
        home_wins=46,
        home_losses=36,
        quarter=2,
        clock="0:00",
    ),

    # Third Quarter
    BasketballGame(
        away="CLE",
        home="IND",
        status="Live",
        start_time="",
        date="",
        away_score=79,
        home_score=83,
        away_wins=53,
        away_losses=29,
        home_wins=47,
        home_losses=35,
        quarter=3,
        clock="2:54",
    ),

    # Fourth Quarter
    BasketballGame(
        away="OKC",
        home="MIN",
        status="Live",
        start_time="",
        date="",
        away_score=104,
        home_score=101,
        away_wins=58,
        away_losses=24,
        home_wins=56,
        home_losses=26,
        quarter=4,
        clock="1:42",
    ),

    # Close Finish
    BasketballGame(
        away="SAC",
        home="LAC",
        status="Live",
        start_time="",
        date="",
        away_score=112,
        home_score=112,
        away_wins=45,
        away_losses=37,
        home_wins=47,
        home_losses=35,
        quarter=4,
        clock="0:12",
    ),

    # Overtime
    BasketballGame(
        away="MEM",
        home="NO",
        status="Live",
        start_time="",
        date="",
        away_score=118,
        home_score=118,
        away_wins=41,
        away_losses=41,
        home_wins=40,
        home_losses=42,
        quarter=5,
        clock="2:11",
    ),

    # Double Overtime
    BasketballGame(
        away="POR",
        home="UTA",
        status="Live",
        start_time="",
        date="",
        away_score=126,
        home_score=126,
        away_wins=32,
        away_losses=50,
        home_wins=31,
        home_losses=51,
        quarter=6,
        clock="1:09",
    ),

    # Final
    BasketballGame(
        away="ATL",
        home="ORL",
        status="Final",
        start_time="",
        date="",
        away_score=113,
        home_score=107,
        away_wins=43,
        away_losses=39,
        home_wins=48,
        home_losses=34,
    ),

    BasketballGame(
        away="HOU",
        home="SA",
        status="Final",
        start_time="",
        date="",
        away_score=127,
        home_score=109,
        away_wins=54,
        away_losses=28,
        home_wins=24,
        home_losses=58,
    ),

]