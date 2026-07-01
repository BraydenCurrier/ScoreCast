from soccer.models import SoccerGame

TEST_GAMES_SOCCER = [

    SoccerGame(
        away="USA",
        home="MEX",

        away_score=2,
        home_score=1,

        status="67'",
        start_time="",
        date="",

        minute=67,
        stoppage="",

        tournament="FIFA WORLD CUP",
        stage="GROUP A",
    ),

    SoccerGame(
        away="ENG",
        home="FRA",

        away_score=1,
        home_score=1,

        status="90'+4'",
        start_time="",
        date="",

        minute=90,
        stoppage="+4",

        tournament="FIFA WORLD CUP",
        stage="QUARTERFINAL",
    ),

    SoccerGame(
        away="BRA",
        home="ARG",

        away_score=0,
        home_score=2,

        status="HT",
        start_time="",
        date="",

        minute=45,
        stoppage="",

        tournament="FIFA WORLD CUP",
        stage="SEMIFINAL",
    ),

    SoccerGame(
        away="ESP",
        home="GER",

        away_score=3,
        home_score=2,

        status="FT",
        start_time="",
        date="",

        minute=90,
        stoppage="",

        tournament="FIFA WORLD CUP",
        stage="ROUND OF 16",
    ),

    SoccerGame(
        away="POR",
        home="NED",

        away_score=0,
        home_score=0,

        status="3:00 PM",
        start_time="3:00 PM",
        date="JUN 24",

        minute=0,
        stoppage="",

        tournament="FIFA WORLD CUP",
        stage="GROUP C",
    ),

    SoccerGame(
        away="JPN",
        home="KOR",

        away_score=0,
        home_score=0,

        status="7:30 PM",
        start_time="7:30 PM",
        date="JUN 26",

        minute=0,
        stoppage="",

        tournament="FIFA WORLD CUP",
        stage="GROUP D",
    ),

    SoccerGame(
        away="ITA",
        home="CRO",

        away_score=0,
        home_score=0,

        status="2:00 PM",
        start_time="2:00 PM",
        date="JUL 10",

        minute=0,
        stoppage="",

        tournament="FIFA WORLD CUP",
        stage="FINAL",
    ),
]