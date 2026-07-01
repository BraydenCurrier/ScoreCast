from common.matrix import create_matrix
from alerts.renderer import play_touchdown_fireworks

matrix = create_matrix()

ALERTS = [
    (
        "DAL",
        "Dak Prescott pass complete short right to CeeDee Lamb for 18 yards, touchdown."
    ),
    (
        "GB",
        "Jordan Love pass complete deep middle to Christian Watson for 32 yards, touchdown."
    ),
    (
        "PIT",
        "Russell Wilson pass complete short left to George Pickens for 24 yards, touchdown."
    ),
    (
        "BAL",
        "Lamar Jackson scrambles up the middle for 12 yards, touchdown."
    ),
    (
        "SF",
        "Christian McCaffrey left tackle for 4 yards, touchdown."
    ),
    (
        "DET",
        "Jahmyr Gibbs right end for 41 yards, touchdown."
    ),
]

while True:
    for team, message in ALERTS:
        print(f"{team}: {message}")
        play_touchdown_fireworks(matrix, team, message)