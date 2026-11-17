# GameLine Pro

### Live sports. Your teams. Your display.

**GameLine Pro** is a Raspberry Pi-powered RGB LED matrix dashboard for sports fans. It brings live scores, game details, personalized player updates, fantasy football, sports bet tracking, and everyday information to a physical LED display—managed from a built-in, mobile-friendly web dashboard.

The source repository is named **ScoreCast**; **GameLine Pro** is the product name used throughout the application.

> A dedicated sports display that keeps the games and information you care about in view without needing a TV or an open browser tab.

## What it does

GameLine Pro combines background data collection, sport-specific graphics, and an RGB matrix display engine. Choose what appears on your board, customize its behavior from your phone, and let the Raspberry Pi run it continuously.

### Live sports and game views

- **NFL** — scores, schedules, game status, and football-specific views.
- **College football (CFB)** — scores, conferences, team branding, and game details.
- **NBA** — scores and basketball-specific game/focus layouts.
- **NHL** — scores and hockey-specific game/focus layouts.
- **MLB** — scores, innings, and baseball-specific game/focus layouts.
- **College basketball (CBB)** — scores and conference filtering.
- **Soccer** — match scores and league selection.
- **PGA golf** — tournament information and golf-specific rendering.

Game and team selection, favorites, and ordering are controlled through the dashboard. The project includes extensive local team and broadcast logo assets.

### Personalized content

- **Game focus views:** Highlight selected games with layouts tailored to the sport.
- **Player cards:** Display selected player information on the LED matrix.
- **Alerts:** Configure team and player-related alerts and on-board notifications.
- **Fantasy football:** Connect supported ESPN fantasy data and display fantasy information.
- **Sports bet tracker:** Log bets you've already placed, monitor supported markets against live game statistics, and review your results.
- **Custom messages:** Create messages and manage uploaded images for the display.
- **Clock themes and countdowns:** Display clocks, themed clock layouts, and countdowns.
- **Weather and stocks:** Include non-sports information alongside your sports content.
- **Display modes:** Configure how different content and views are shown.

Some features depend on the availability and completeness of external data feeds.

## Web dashboard

GameLine Pro includes a Flask-based web interface that you can access from a device on the same network. It provides pages for:

| Area | What you can manage |
| --- | --- |
| Games | Select, order, and filter sports content |
| Favorites | Choose the teams and games you care about |
| Focus | Configure focused game presentations |
| Players | Manage player cards |
| Alerts | Configure on-display notifications |
| Fantasy | Set up and view fantasy integrations |
| Bets | Track wagers and review betting performance |
| Modes | Manage display behavior and content modes |
| Messages | Create custom messages and images |
| Clock Themes | Preview and select clock styles |
| Stocks | Choose market symbols to display |
| Logos | Manage team logo assets |
| Settings | Adjust the display and system configuration |

The application also includes user profiles and sign-in functionality. The first account created is the root profile, which can manage additional users.

## Sports bet tracking

GameLine Pro includes a **bet tracker, not a sportsbook**. It does not place bets, handle payments, or connect to betting accounts to submit wagers.

You can enter singles and parlays, including your own lines, odds, and stakes. For supported games and markets, the application uses available game and player statistics to update individual legs, settle results, and calculate historical analytics.

Supported tracking includes:

- **NFL / CFB:** Passing, rushing, and receiving statistics; touchdowns; and selected game/team markets.
- **NBA:** Points, rebounds, assists, three-pointers, and other supported player and game markets.
- **NHL:** Goals, assists, points, shots, saves, and supported game markets.
- **MLB:** Batting and pitching statistics and supported game markets.

The tracker includes win/loss/push/void handling, manual result overrides, parlay settlement, and performance metrics such as record, hit rate, net results, and ROI. Optional LED notifications can highlight bet events without overriding higher-priority display content.

**GameLine Estimate** is an experimental, model-based live hit estimate derived from available player statistics and game progress. It is not a sportsbook probability or a guarantee of an outcome.

## Hardware

GameLine Pro is designed for a **Raspberry Pi driving a HUB75-style RGB LED matrix**.

The existing installation documentation targets:

- Raspberry Pi 4 (2 GB or better)
- Raspberry Pi OS Lite, 64-bit
- Compatible RGB LED matrix panel
- Electrodragon RGB Matrix Panel Drive Board
- Suitable 5V power supply for your panel
- Network access for setup and live data

Check your panel dimensions, wiring, power requirements, and driver compatibility before installing. Matrix hardware is not included with this repository.

## Installation

### Option 1: Install on Raspberry Pi OS Lite

1. Flash **Raspberry Pi OS Lite (64-bit)** to your Pi and boot it with network access.
2. Update the operating system:

   ```bash
   sudo apt update
   sudo apt upgrade -y
   sudo reboot
   ```

3. Clone the project:

   ```bash
   git clone https://github.com/BraydenCurrier/ScoreCast.git
   cd ScoreCast
   ```

4. Run the included installer:

   ```bash
   sudo bash scripts/install.sh
   ```

The installer provisions the application's dependencies, Python environment, display support, persistent state, and systemd services. It is intended for a compatible Raspberry Pi OS installation and requires elevated privileges.

### Option 2: Raspberry Pi image build

The repository also includes a GitHub Actions workflow and image-stage scripts for building a configured Raspberry Pi image. See `.github/workflows/build-pi-image.yml` and `image/stage-scorecast/` for the image-build implementation. This is a separate deployment path from running the installer on an existing OS.

## First-time setup

After installation, open the dashboard from a phone or computer on the same local network:

```text
http://<raspberry-pi-ip>:8080
```

Find the Pi's IP address with:

```bash
hostname -I
```

On first use, create your administrator account, then configure your preferred sports, favorites, display modes, and matrix settings.

The codebase also includes an on-device network onboarding flow with a setup hotspot, Wi-Fi selection, and QR-based setup support for deployments that use that provisioning path.

**Security:** Keep the dashboard and setup interfaces on a trusted local network. Do not forward ports 80 or 8080 from your router to the public internet.

## Everyday operation

Once installed, GameLine Pro runs as a systemd service and is configured to restart automatically if the application exits.

```bash
# Check whether GameLine Pro is running
sudo systemctl status scorecast

# Follow application logs
sudo journalctl -u scorecast -f

# Restart the application
sudo systemctl restart scorecast
```

The dashboard also exposes supported system controls and update functionality. The repository contains a release updater and a separate update service:

```bash
sudo systemctl start scorecast-update
```

Application data is stored separately from the installed code, allowing normal application updates to preserve persistent settings. The bet tracker uses SQLite (normally `/var/lib/scorecast/bets.sqlite`).

## How it works

```text
Sports APIs / External Data
             |
             v
  Background data refresh
             |
             v
    Normalized game state
             |
             +------> Alerts / Bets / Fantasy
             |
             v
  Sport-specific renderers
             |
             v
   Display and mode engine
             |
             v
      RGB LED matrix

 Phone / Browser
       |
       v
 Flask web dashboard
       |
       v
 Settings, content selection, and system controls
```

The application uses dedicated modules for each sport, shared display utilities, a mode engine, and a Flask dashboard. External data is refreshed in the background so the display can continue presenting content while new information is retrieved.

## Project structure

```text
ScoreCast/
├── assets/                 # Team, broadcast, and display assets
├── image/                  # Raspberry Pi image-build stage
├── scripts/                # Installation and build helpers
├── setup/                  # Additional setup scripts
├── src/
│   ├── main.py             # Application entry point
│   ├── web/                 # Flask dashboard and frontend assets
│   ├── common/              # Display, configuration, weather, and shared utilities
│   ├── modes/               # Display mode engine and controls
│   ├── setup/               # Network onboarding and setup workflow
│   ├── alerts/              # Team/player alerts and notifications
│   ├── bets/                # Bet tracking, grading, and analytics
│   ├── fantasy/             # Fantasy integrations and rendering
│   ├── players/             # Player cards and rendering
│   ├── messages/            # Custom display messages
│   ├── clock_themes/        # Clock theme controls
│   ├── nfl/ nba/ nhl/       # Professional sports modules
│   ├── mlb/ cfb/ cbb/       # Baseball and college sports modules
│   ├── soccer/ pga/         # Soccer and golf modules
│   ├── stocks/              # Stock data and display rendering
│   ├── updater/             # Release update management
│   └── music/               # Reserved integration modules (not implemented)
├── systemd/                # Runtime and updater service definitions
├── requirements.txt        # Python dependencies
└── README.md
```

## Technology

- **Python** for the application, integrations, and rendering logic
- **Flask** for the dashboard and HTTP endpoints
- **Pillow** for image processing and graphics
- **Requests** for HTTP data access
- **SQLite** for persistent bet-tracking data
- **C++ native display helper** for panel shifting
- **systemd** for background operation and service recovery
- **Raspberry Pi RGB matrix libraries** for hardware output

The code integrates with ESPN-related sports data, MLB data, and NHL data, alongside other feature-specific sources. External APIs can change, become unavailable, or impose limits.

## Development and tests

The repository contains Python test modules alongside many of its feature packages (`test_*.py`). A basic dependency setup for code inspection or non-hardware testing is:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Many runtime paths are Raspberry Pi and LED-matrix specific, so installing the Python requirements alone does **not** reproduce a complete working display on a desktop computer. Some tests may also require additional dependencies, hardware mocks, or network access.

## Current implementation notes

- The repository contains functioning code paths for the sports display, web dashboard, setup, alerts, bets, clocks, messages, and other listed modules, but individual features may depend on live providers or specific hardware.
- The `src/music/` Spotify-related files are currently empty placeholders. Music playback or Spotify integration should **not** be considered a released feature based on this code.
- The project contains an updater, provisioning utilities, and image-building infrastructure; deployment behavior depends on the installation method and environment.
- This README documents the uploaded codebase. It is not a claim that every feature has been tested on every supported panel or Raspberry Pi model.

## Troubleshooting

**Dashboard won't load:** Confirm the Pi is connected to the network, check its IP address, and verify that `scorecast` is running.

**LED panel is blank:** Check panel power, HUB75 connections, driver-board compatibility, and configured display parameters. Review the application logs for initialization errors.

**Scores are missing or stale:** Confirm internet connectivity and check the logs. Live data depends on external APIs and may not be available for every game or market.

**Update fails:** Check the updater service and logs, and verify that the Pi has network access and sufficient disk space.

## License

The previous README identified this project as MIT-licensed, but the uploaded archive does not include a standalone `LICENSE` file. Add the intended license text to the repository before treating the license declaration as complete.

---

**GameLine Pro** — your sports, your information, your LED display.
