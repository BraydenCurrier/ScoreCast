from rgbmatrix import RGBMatrix, RGBMatrixOptions
from common.config import ROWS, COLS, CHAIN_LENGTH, PARALLEL, GPIO_SLOWDOWN, HARDWARE_MAPPING

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

    return RGBMatrix(options=options)