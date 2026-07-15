from dataclasses import dataclass


@dataclass(frozen=True)
class PossessionAlert:
    game_id: str
    alert_type: str
    team: str
    opponent: str
    headline: str
    detail: str
    possession_label: str
    chant: tuple[str, ...]
    primary: tuple[int, int, int]
    accent: tuple[int, int, int]
    down: int
    distance: int
    yardline_side: str
    yardline_number: int
    quarter: int
    clock: str
    created_at: float
    chant_frame_seconds: float
    details_frame_seconds: float

    @property
    def total_duration(self) -> float:
        word_duration = max(
            0.1,
            self.chant_frame_seconds,
        )
        blank_duration = max(
            0.05,
            word_duration * 0.30,
        )

        chant_duration = len(self.chant) * (
            word_duration + blank_duration
        )

        return (
            chant_duration
            + self.details_frame_seconds
        )