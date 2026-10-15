<div align="center">

# ScoreCast

**Live sports. Real-time tracking. One LED display.**

A Raspberry Pi-powered sports dashboard for RGB LED matrices, featuring live scores, game information, sports news, betting odds, and a built-in bet tracker—all managed through a web interface.

[Getting Started](#getting-started) · [Features](#features) · [Bet Tracker](#sports-bet-tracker) · [Troubleshooting](#troubleshooting)

</div>

---

## Overview

ScoreCast turns an RGB LED matrix into a configurable sports ticker. Follow games across major professional and college leagues, adjust what appears on your display from a browser, and track bets you have already placed without leaving the ScoreCast dashboard.

Built for Raspberry Pi, ScoreCast combines background sports-data updates, cached rendering, and a systemd-managed service for an always-on display.

## Features

| Feature | Description |
| --- | --- |
| **Live scores** | MLB, NFL, NBA, NHL, college football, and soccer coverage. |
| **Customizable ticker** | Show or hide games and drag to reorder them. |
| **Web dashboard** | Manage the display from a phone, tablet, or computer on your network. |
| **Display controls** | Adjust brightness, scrolling speed, and refresh intervals. |
| **Sports information** | Display supported odds and news content. |
| **Bet tracking** | Track single bets and parlays using supported game and player statistics. |
| **Bet analytics** | Review settled results, hit rates, net performance, and ROI where sufficient data is available. |
| **LED notifications** | Optionally show open bets and brief HIT/WON notices. |
| **Background updates** | Refresh sports data without stopping the ticker. |
| **Managed installation** | Start at boot and install updates from the web dashboard. |

### Supported sports

- MLB — Major League Baseball
- NFL — National Football League
- NBA — National Basketball Association
- NHL — National Hockey League
- College football
- Soccer

Availability and detail vary by sport and upstream data provider.

## Hardware requirements

The documented hardware setup uses:

- Raspberry Pi 4 (2 GB RAM)
- Raspberry Pi OS Lite (64-bit)
- Compatible RGB LED matrix panel
- Electrodragon RGB Matrix Panel Drive Board
- Appropriate 5V power supply for the panel
- Network connection for sports data and dashboard access

> **Hardware note:** Confirm the power requirements and wiring for your specific matrix and driver board before connecting power. The installation process may disable built-in Raspberry Pi audio and change boot configuration to improve matrix timing.

## Getting started

### 1. Prepare your Raspberry Pi

Install **Raspberry Pi OS Lite (64-bit)** using Raspberry Pi Imager. Enable SSH if you plan to manage the Pi remotely, and connect it to your network.

Update the operating system:

```bash
sudo apt update
sudo apt upgrade -y
sudo reboot
```

Reconnect to the Pi after it restarts.

### 2. Install ScoreCast

Clone the repository and run the included installer:

```bash
git clone https://github.com/BraydenCurrier/ScoreCast.git
cd ScoreCast
chmod +x scripts/install.sh
sudo ./scripts/install.sh
```

The installer prepares system dependencies, builds the RGB matrix library, creates a Python virtual environment, selects the latest semantic-version release tag, configures persistent storage, and registers the ScoreCast and updater systemd services.

**Important:** The installer may require a reboot to apply hardware-related configuration. If it does, installation is designed to finish automatically after the reboot. Wait for the service to start before opening the dashboard.

### 3. Open the dashboard

Find the Pi's IP address:

```bash
hostname -I
```

From another device on the same network, visit:

```text
http://<raspberry-pi-ip>:8080
```

On first visit, use the initial setup password:

```text
ticker123
```

Then create your own username and password. The first account is the **root administrator** and can add other users.

> **Security:** Complete initial setup promptly, use a strong unique password, and keep the dashboard on a trusted local network. Do not expose port 8080 directly to the public internet.

### 4. Customize your display

Use the dashboard to choose visible games, reorder them, configure scrolling and brightness, and adjust available odds, news, and bet-tracking options.

## Sports Bet Tracker

ScoreCast includes a tracker for bets **already placed elsewhere**. It does not accept wagers, hold funds, or connect to a sportsbook to place bets.

### Track singles and parlays

From the signed-in dashboard, open **Bets** to add a single bet or parlay. Select a supported league and event, choose an available market, and enter your own line and odds.

| League | Supported market examples |
| --- | --- |
| **NFL / College Football** | Passing, rushing and receiving yards; touchdowns; receptions; passing attempts and completions; interceptions; moneyline, spread and totals. |
| **NBA** | Points, rebounds, assists, three-pointers, steals, blocks, turnovers, combined player statistics, moneyline, spread and totals. |
| **NHL** | Goals, assists, points, shots, saves, moneyline, spread and totals. |
| **MLB** | Hits, total bases, home runs, runs, RBIs, walks, strikeouts, pitcher statistics, moneyline, spread and totals. |

Only markets that ScoreCast can evaluate from its available data feeds are offered. Market availability depends on the game and source data.

### Automatic grading

During sports refreshes, ScoreCast groups open bets by event, retrieves available game and player statistics, and updates matching bet legs.

- Missing statistics are not automatically treated as losses.
- Overs on counting statistics can settle as hits once the threshold is passed.
- Unders generally wait until the event is final, unless already impossible to win.
- A losing leg causes a parlay to lose; pushed or voided legs are excluded from the winning-leg count.
- Manual overrides let you record a sportsbook's official won, lost, pushed, or voided result separately from the automatic grade.

**Always use your sportsbook's official settlement as the authoritative result.** Feed delays, corrections, and market-specific rules can cause differences.

### Analytics and live estimates

The tracker can report record, hit rate, net result, and ROI. Monetary calculations exclude entries without the stake and odds needed for a meaningful result. Historical labels require a minimum sample of settled results.

Where available, **ScoreCast Estimate** provides a model-based live hit-chance estimate using cached player history, current statistics, and remaining game time. It is not a sportsbook probability, guarantee, or betting recommendation. Same-game parlay legs are not assumed to be independent.

### Bet notifications on the LED matrix

Enable open-bet visibility or brief **HIT / WON** notifications from the Add Bet settings. These notifications are designed not to override higher-priority Alerts or Focus displays.

## Updates

ScoreCast includes a web-based updater. When an update is available:

1. Open the dashboard.
2. Select **Check and Install Update**.
3. Allow the update and service restart to finish.
4. Return to the dashboard when the service is available.

Settings are stored separately from versioned application releases so updates can preserve configuration and bet data.

For service-level troubleshooting, you can also start the updater manually:

```bash
sudo systemctl start scorecast-update
sudo journalctl -u scorecast-update -n 100 --no-pager
```

## Configuration and storage

Default locations used by the installer:

| Path | Purpose |
| --- | --- |
| `/opt/scorecast/` | Managed installation and release directories. |
| `/opt/scorecast/current` | Active application release. |
| `/opt/scorecast/current-venv` | Active Python environment. |
| `/var/lib/scorecast/settings.json` | Persistent application settings. |
| `/var/lib/scorecast/bets.sqlite` | Bet-tracking database. |
| `/etc/systemd/system/scorecast.service` | Main application service. |
| `/etc/systemd/system/scorecast-update.service` | Update service. |

The `SCORECAST_CONFIG_DIR` environment variable controls the application's persistent configuration location where supported.

**Backups:** Back up your persistent settings and bet database before making major system changes. Avoid publishing these files, as they may contain personal configuration or betting history.

## Troubleshooting

Check whether ScoreCast is running:

```bash
sudo systemctl status scorecast
```

Follow application logs:

```bash
sudo journalctl -u scorecast -f
```

Restart the application:

```bash
sudo systemctl restart scorecast
```

Review recent updater logs:

```bash
sudo journalctl -u scorecast-update -n 100 --no-pager
```

If the dashboard is unavailable, verify that the Pi is connected to the network, confirm its IP address with `hostname -I`, and check that the ScoreCast service is active. If the display is blank, also verify the matrix power supply, cable orientation, driver board connections, and service logs.

## Data sources

ScoreCast uses sports data from sources including:

- [ESPN](https://www.espn.com/) — scoreboards, game summaries, and supported statistics.
- [MLB Stats API](https://statsapi.mlb.com/) — MLB game and player data.
- [NHL API](https://api-web.nhle.com/) — NHL data.

Data availability, accuracy, latency, and access are subject to the respective providers. ScoreCast is an independent project and is not affiliated with or endorsed by these organizations.

## Contributing

Contributions, bug reports, and feature suggestions are welcome. Open an [issue](https://github.com/BraydenCurrier/ScoreCast/issues) to describe a bug or proposed improvement, or submit a pull request with a focused change and clear description.

## License

The repository describes ScoreCast as MIT-licensed. Consult the repository's license information for the applicable terms.

---

<div align="center">

**ScoreCast** — Built for sports fans who want the game on display.

[Repository](https://github.com/BraydenCurrier/ScoreCast) · [Report an Issue](https://github.com/BraydenCurrier/ScoreCast/issues)

</div>
