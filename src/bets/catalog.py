from __future__ import annotations

from dataclasses import dataclass


STATUS_PENDING = "pending"
STATUS_LIVE = "live"
STATUS_WON = "won"
STATUS_LOST = "lost"
STATUS_PUSH = "push"
STATUS_VOID = "void"
STATUS_REVIEW = "review"

OPEN_STATUSES = frozenset({STATUS_PENDING, STATUS_LIVE, STATUS_REVIEW})
SETTLED_STATUSES = frozenset({
    STATUS_WON,
    STATUS_LOST,
    STATUS_PUSH,
    STATUS_VOID,
})

KIND_SINGLE = "single"
KIND_PARLAY = "parlay"

SCOPE_PLAYER = "player"
SCOPE_GAME = "game"

DIR_OVER = "over"
DIR_UNDER = "under"
DIR_ML_HOME = "ml_home"
DIR_ML_AWAY = "ml_away"
DIR_SPREAD_HOME = "spread_home"
DIR_SPREAD_AWAY = "spread_away"
DIR_TOTAL_OVER = "total_over"
DIR_TOTAL_UNDER = "total_under"
DIR_TEAM_HOME_OVER = "team_home_over"
DIR_TEAM_HOME_UNDER = "team_home_under"
DIR_TEAM_AWAY_OVER = "team_away_over"
DIR_TEAM_AWAY_UNDER = "team_away_under"

LEAGUES = ("nfl", "cfb", "nba", "mlb", "nhl")

LEAGUE_LABELS = {
    "nfl": "NFL",
    "cfb": "College Football",
    "nba": "NBA",
    "mlb": "MLB",
    "nhl": "NHL",
}


@dataclass(frozen=True)
class Market:
    key: str
    label: str
    short_label: str
    scope: str
    unit: str = ""
    monotonic: bool = True
    group: str = "offense"


MARKETS = {
    "pass_yds": Market("pass_yds", "Pass YDS", "PASS YDS", SCOPE_PLAYER, "YDS"),
    "pass_td": Market("pass_td", "Pass TD", "PASS TD", SCOPE_PLAYER, "TD"),
    "pass_comp": Market("pass_comp", "Pass COMP", "PASS COMP", SCOPE_PLAYER),
    "pass_att": Market("pass_att", "Pass ATT", "PASS ATT", SCOPE_PLAYER),
    "pass_int": Market("pass_int", "Pass INT", "PASS INT", SCOPE_PLAYER),
    "rush_yds": Market("rush_yds", "Rush YDS", "RUSH YDS", SCOPE_PLAYER, "YDS"),
    "rush_att": Market("rush_att", "Rush ATT", "RUSH ATT", SCOPE_PLAYER),
    "rush_td": Market("rush_td", "Rush TD", "RUSH TD", SCOPE_PLAYER, "TD"),
    "rec_yds": Market("rec_yds", "Rec YDS", "REC YDS", SCOPE_PLAYER, "YDS"),
    "receptions": Market("receptions", "Rec", "REC", SCOPE_PLAYER),
    "rec_td": Market("rec_td", "Rec TD", "REC TD", SCOPE_PLAYER, "TD"),
    "rush_rec_yds": Market("rush_rec_yds", "Rush+Rec YDS", "R+R YDS", SCOPE_PLAYER, "YDS"),
    "anytime_td": Market("anytime_td", "Anytime TD", "ANY TD", SCOPE_PLAYER, "TD"),
    "points": Market("points", "Points", "PTS", SCOPE_PLAYER, "PTS"),
    "rebounds": Market("rebounds", "Rebounds", "REB", SCOPE_PLAYER),
    "assists": Market("assists", "Assists", "AST", SCOPE_PLAYER),
    "threes": Market("threes", "Made Threes", "3PM", SCOPE_PLAYER),
    "steals": Market("steals", "Steals", "STL", SCOPE_PLAYER),
    "blocks": Market("blocks", "Blocks", "BLK", SCOPE_PLAYER),
    "turnovers": Market("turnovers", "Turnovers", "TO", SCOPE_PLAYER),
    "pra": Market("pra", "Pts + Reb + Ast", "P+R+A", SCOPE_PLAYER),
    "pr": Market("pr", "Pts + Reb", "P+R", SCOPE_PLAYER),
    "pa": Market("pa", "Pts + Ast", "P+A", SCOPE_PLAYER),
    "ra": Market("ra", "Reb + Ast", "R+A", SCOPE_PLAYER),
    "hits": Market("hits", "Hits", "H", SCOPE_PLAYER),
    "total_bases": Market("total_bases", "Total Bases", "TB", SCOPE_PLAYER),
    "home_runs": Market("home_runs", "Home Runs", "HR", SCOPE_PLAYER),
    "runs": Market("runs", "Runs", "R", SCOPE_PLAYER),
    "rbi": Market("rbi", "RBI", "RBI", SCOPE_PLAYER),
    "batter_bb": Market("batter_bb", "Walks", "BB", SCOPE_PLAYER),
    "batter_k": Market("batter_k", "Strikeouts (batter)", "K", SCOPE_PLAYER),
    "pitcher_k": Market("pitcher_k", "Strikeouts (pitcher)", "K", SCOPE_PLAYER),
    "pitcher_bb": Market("pitcher_bb", "Walks Allowed", "BB", SCOPE_PLAYER),
    "pitcher_hits": Market("pitcher_hits", "Hits Allowed", "H", SCOPE_PLAYER),
    "goals": Market("goals", "Goals", "G", SCOPE_PLAYER),
    "hockey_assists": Market("hockey_assists", "Assists", "A", SCOPE_PLAYER),
    "hockey_points": Market("hockey_points", "Points", "P", SCOPE_PLAYER),
    "shots": Market("shots", "Shots", "SOG", SCOPE_PLAYER),
    "saves": Market("saves", "Saves", "SV", SCOPE_PLAYER),
    "moneyline": Market("moneyline", "Moneyline", "ML", SCOPE_GAME, monotonic=False),
    "spread": Market("spread", "Spread", "SPREAD", SCOPE_GAME, monotonic=False),
    "total": Market("total", "Game Total", "TOTAL", SCOPE_GAME),
    "team_total": Market("team_total", "Team Total", "TEAM TOT", SCOPE_GAME),
}

LEAGUE_MARKETS = {
    "nfl": [
        "pass_yds", "pass_td", "pass_comp", "pass_att", "pass_int",
        "rush_yds", "rush_att", "rush_td",
        "rec_yds", "receptions", "rec_td", "rush_rec_yds", "anytime_td",
        "moneyline", "spread", "total", "team_total",
    ],
    "cfb": [
        "pass_yds", "pass_td", "pass_comp", "pass_att", "pass_int",
        "rush_yds", "rush_att", "rush_td",
        "rec_yds", "receptions", "rec_td", "rush_rec_yds", "anytime_td",
        "moneyline", "spread", "total", "team_total",
    ],
    "nba": [
        "points", "rebounds", "assists", "threes", "steals", "blocks",
        "turnovers", "pra", "pr", "pa", "ra",
        "moneyline", "spread", "total", "team_total",
    ],
    "mlb": [
        "hits", "total_bases", "home_runs", "runs", "rbi",
        "batter_bb", "batter_k", "pitcher_k", "pitcher_bb", "pitcher_hits",
        "moneyline", "spread", "total", "team_total",
    ],
    "nhl": [
        "goals", "hockey_assists", "hockey_points", "shots", "saves",
        "moneyline", "spread", "total", "team_total",
    ],
}

PLAYER_DIRECTIONS = (
    (DIR_OVER, "Over"),
    (DIR_UNDER, "Under"),
)

GAME_DIRECTIONS = {
    "moneyline": (
        (DIR_ML_AWAY, "Away moneyline"),
        (DIR_ML_HOME, "Home moneyline"),
    ),
    "spread": (
        (DIR_SPREAD_AWAY, "Away spread"),
        (DIR_SPREAD_HOME, "Home spread"),
    ),
    "total": (
        (DIR_TOTAL_OVER, "Over"),
        (DIR_TOTAL_UNDER, "Under"),
    ),
    "team_total": (
        (DIR_TEAM_AWAY_OVER, "Away over"),
        (DIR_TEAM_AWAY_UNDER, "Away under"),
        (DIR_TEAM_HOME_OVER, "Home over"),
        (DIR_TEAM_HOME_UNDER, "Home under"),
    ),
}


def market_for(key: str) -> Market:
    market = MARKETS.get(str(key or "").strip())
    if market is None:
        raise ValueError("Unsupported market.")
    return market


def markets_for_league(league: str, scope: str | None = None) -> list[Market]:
    keys = LEAGUE_MARKETS.get(str(league or "").lower(), [])
    markets = [MARKETS[key] for key in keys if key in MARKETS]
    if scope:
        markets = [market for market in markets if market.scope == scope]
    return markets


def positions_for_market(league: str, market_key: str) -> tuple[str, ...] | None:
    """Roster positions that can reasonably have this prop. None means any."""
    league = str(league or "").lower()
    key = str(market_key or "").strip()
    if league in {"nfl", "cfb"}:
        football = {
            "pass_yds": ("QB", "ATH"),
            "pass_td": ("QB", "ATH"),
            "pass_comp": ("QB", "ATH"),
            "pass_att": ("QB", "ATH"),
            "pass_int": ("QB", "ATH"),
            "rush_yds": ("RB", "FB", "HB", "TB", "QB", "WR", "ATH"),
            "rush_att": ("RB", "FB", "HB", "TB", "QB", "WR", "ATH"),
            "rush_td": ("RB", "FB", "HB", "TB", "QB", "WR", "ATH"),
            "rec_yds": ("WR", "TE", "RB", "FB", "ATH"),
            "receptions": ("WR", "TE", "RB", "FB", "ATH"),
            "rec_td": ("WR", "TE", "RB", "FB", "ATH"),
            "rush_rec_yds": ("RB", "FB", "HB", "WR", "TE", "ATH"),
            "anytime_td": ("QB", "RB", "FB", "HB", "WR", "TE", "ATH"),
        }
        return football.get(key)
    if league == "mlb":
        pitchers = ("P", "SP", "RP", "LHP", "RHP", "TWP")
        hitters = (
            "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH",
            "OF", "INF", "UTIL", "PH", "PR",
        )
        if key.startswith("pitcher_"):
            return pitchers
        if key in {
            "hits", "total_bases", "home_runs", "runs", "rbi",
            "batter_bb", "batter_k",
        }:
            return hitters
        return None
    if league == "nhl":
        if key == "saves":
            return ("G",)
        if key in {"goals", "hockey_assists", "hockey_points", "shots"}:
            return ("C", "LW", "RW", "F", "W", "D")
        return None
    return None


def directions_for(market_key: str) -> tuple[tuple[str, str], ...]:
    market = market_for(market_key)
    if market.scope == SCOPE_PLAYER:
        return PLAYER_DIRECTIONS
    return GAME_DIRECTIONS.get(market.key, PLAYER_DIRECTIONS)


def is_over_direction(direction: str) -> bool:
    return str(direction) in {
        DIR_OVER,
        DIR_TOTAL_OVER,
        DIR_TEAM_HOME_OVER,
        DIR_TEAM_AWAY_OVER,
    }


def is_under_direction(direction: str) -> bool:
    return str(direction) in {
        DIR_UNDER,
        DIR_TOTAL_UNDER,
        DIR_TEAM_HOME_UNDER,
        DIR_TEAM_AWAY_UNDER,
    }
