from rgbmatrix import RGBMatrix, RGBMatrixOptions
from common.config import ROWS, COLS, CHAIN_LENGTH, PARALLEL, GPIO_SLOWDOWN, HARDWARE_MAPPING

# Idle refresh on this panel is about 190Hz and falls to about 165Hz while
# memory is busy. Capping below that floor keeps every refresh the same
# length, so brightness and scroll timing stay steady.
PANEL_REFRESH_HZ = 140

def create_matrix():
    options = RGBMatrixOptions()
    options.rows = ROWS
    options.cols = COLS
    options.chain_length = CHAIN_LENGTH
    options.parallel = PARALLEL
    options.hardware_mapping = HARDWARE_MAPPING
    options.gpio_slowdown = GPIO_SLOWDOWN
    options.disable_hardware_pulsing = False

    options.pwm_bits = 8
    options.pwm_lsb_nanoseconds = 130
    options.brightness = 60
    options.limit_refresh_rate_hz = PANEL_REFRESH_HZ

    options.drop_privileges = False

    return RGBMatrix(options=options)