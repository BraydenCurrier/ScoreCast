from bets.providers.espn import EspnProvider
from bets.providers.mlb import MlbProvider


_PROVIDERS = {
    "nfl": EspnProvider("nfl"),
    "cfb": EspnProvider("cfb"),
    "nba": EspnProvider("nba"),
    "nhl": EspnProvider("nhl"),
    "mlb": MlbProvider(),
}


def get_provider(league: str):
    provider = _PROVIDERS.get(str(league or "").lower())
    if provider is None:
        raise ValueError("Unsupported league.")
    return provider


def supported_leagues() -> list[str]:
    return list(_PROVIDERS.keys())
