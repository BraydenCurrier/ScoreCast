from pga.models import GolfPlayer, GolfTournament


TEST_GAMES_PGA = [
    GolfTournament(
        event_id="sample",
        name="Baycurrent Classic",
        status="Live",
        logo_url="",
        players=(
            GolfPlayer("BRENNAN", "1", "-16", -16, "68", True),
            GolfPlayer("MITCHELL", "T2", "-15", -15, "14", False),
            GolfPlayer("BRIDGEMAN", "T2", "-12", -12, "9", False),
            GolfPlayer("SCHAUFFELE", "4", "E", 0, "67", True),
            GolfPlayer("HARMAN", "T5", "+2", 2, "3", False),
            GolfPlayer("GERARD", "T5", "+2", 2, "72", True),
        ),
    ),
]
