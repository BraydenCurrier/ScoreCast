import sys
import threading
import time
from PIL import Image, ImageDraw

from common.matrix import create_matrix
from cfb import cfb_logos  # Import your generated logo database

# 1. Initialize the physical panel
matrix = create_matrix()

# 2. Extract all logo arrays dynamically from nfl_logos.py
# This filters out internal python variables and grabs only your team constants
logo_keys = [key for key in dir(cfb_logos) if key.startswith("LOGO_")]
logo_keys.sort()  # Alphabetical order

if not logo_keys:
    print("Error: No logos found in nfl_logos.py! Did you run the scraper script first?")
    sys.exit(1)

current_idx = 0
running = True

print(f"Loaded {len(logo_keys)} MLB team logos for testing.")
print("Commands:")
print("  n = next logo")
print("  p = previous logo")
print("  q = quit")
print("")

# 3. Input Thread for cycling through logos without blocking the matrix refresh
def input_thread():
    global current_idx, running
    while running:
        try:
            cmd = input("> ").strip().lower()
            if cmd == "n":
                current_idx = (current_idx + 1) % len(logo_keys)
                print(f"Showing: {logo_keys[current_idx]} ({current_idx + 1}/{len(logo_keys)})")
            elif cmd == "p":
                current_idx = (current_idx - 1) % len(logo_keys)
                print(f"Showing: {logo_keys[current_idx]} ({current_idx + 1}/{len(logo_keys)})")
            elif cmd == "q":
                running = False
                break
        except EOFError:
            break

threading.Thread(target=input_thread, daemon=True).start()

# 4. Main Display Loop
try:
    while running:
        # Create a clean black 64x32 canvas
        image = Image.new("RGB", (64, 32), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Get current logo data
        current_key = logo_keys[current_idx]
        logo_data = getattr(cfb_logos, current_key)
        
        # Center Calculation for a 30x30 logo on a 64x32 screen:
        # X: (64 - 30) / 2 = 17
        # Y: (32 - 30) / 2 = 1
        x_start = 1
        y_start = 1
        
        # Draw the logo pixel-by-pixel
        for y, row in enumerate(logo_data):
            for x, rgb_color in enumerate(row):
                # Ignore pure black if you want a transparent layer effect,
                # but draw it here to see the full bounded output box
                draw.point((x_start + x, y_start + y), fill=rgb_color)
                
        # Push frame to the physical LED Matrix
        matrix.SetImage(image)
        
        # 20 FPS refresh rate
        time.sleep(0.05)

except KeyboardInterrupt:
    pass

print("\nLogo test utility closed safely.")