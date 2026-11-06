from dataclasses import dataclass

from nba.models import BasketballGame


@dataclass
class CollegeBasketballGame(BasketballGame):
    """Same board fields as an NBA game. Four timeout pips, school names."""

    timeout_slots: int = 4
