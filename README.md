# ScoreCast

> **Turn any RGB LED matrix into a live sports dashboard with live scores, betting odds, breaking news, and more.**

ScoreCast is a Raspberry Pi-powered sports ticker designed for RGB LED matrices. It displays live scores from multiple sports, betting odds, breaking news, and upcoming features like fantasy football and Spotify integration—all configurable from a built-in web dashboard.

---

# Features

## 🏆 Live Scores

- ⚾ MLB
- 🏈 NFL
- 🏀 NBA
- 🏒 NHL
- 🏈 College Football
- ⚽ Soccer

All scores update automatically in the background without interrupting scrolling.

---

## 🌐 Built-in Web Dashboard

Control everything from your phone or computer.

- Drag & drop game ordering
- Hide/show games
- Brightness control
- Scroll speed adjustment
- Refresh interval
- Odds settings
- News settings

No coding required.

---

## ⚡ Performance

Designed specifically for Raspberry Pi.

- Cached rendering
- Smooth 60 FPS scrolling
- Background API refreshing
- Auto starts when the Pi boots

---

# Gallery

Ticker:

<p align="center">
  <img width="800" height="135" alt="ticker" src="https://github.com/user-attachments/assets/99b169b4-8b08-432a-890e-cac1afc06441" />
</p>

Web Dashboard:

<p align="center">
  <img src="https://github.com/user-attachments/assets/f61057ea-ca7c-40a5-8e0b-5d141497fd9d" width="250">
  <img src="https://github.com/user-attachments/assets/5f234f4d-61d1-465c-8521-71f40e43692a" width="250">
  <img src="https://github.com/user-attachments/assets/19ded752-622a-40fc-94bb-d92c6c171061" width="250">
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/313deaa3-5d26-40d3-905d-0aa6f2ea6bc9" width="250">
  <img src="https://github.com/user-attachments/assets/1d4f53c3-1f63-4792-b34c-258b0a1a14a5" width="250">
</p>

---

# Hardware Required

- Raspberry Pi 4 2GB
- Raspberry Pi OS Lite (64-bit)
- RGB LED Matrix
- Electrodragon RGB Matrix Panel Drive Board
- 5V Power Supply

---

# Installation

## 1. Install Raspberry Pi OS Lite

Flash the latest **Raspberry Pi OS Lite (64-bit)** using Raspberry Pi Imager.

Boot the Pi and connect it to the internet.

---

## 2. Update the Pi

```bash
sudo apt update
sudo apt upgrade -y
sudo reboot
```

Reconnect after the reboot.

---

## 3. Download ScoreCast

```bash
git clone https://github.com/BraydenCurrier/ScoreCast.git
cd ScoreCast
```

---

## 4. Run the installer

```bash
chmod +x scripts/install.sh

sudo ./scripts/install.sh
```

The installer automatically:

- Installs all required system packages
- Installs the RGB Matrix library
- Downloads the latest ScoreCast release
- Creates the Python virtual environment
- Configures persistent settings storage
- Installs and enables the ScoreCast systemd service
- Installs the automatic updater service
- Starts ScoreCast

---

## 5. Open the dashboard

Find your Raspberry Pi's IP address:

```bash
hostname -I
```

Open:

```
http://<raspberry-pi-ip>:8080
```

The first visit uses the setup password `ticker123`. ScoreCast then asks you to create a username and password. That first account is the root user and is the only profile that can add more people later.

Everything can now be configured from the web dashboard.

---

# Updating ScoreCast

ScoreCast includes a built-in updater.

When a new version is available:

1. Open the web dashboard.
2. Click **Check and Install Update**.
3. Wait for the update to finish.
4. ScoreCast automatically restarts.
5. All settings are preserved.

No SSH, Git commands, or manual installation steps are required after the initial setup.

---

# Troubleshooting

View the ScoreCast logs:

```bash
sudo journalctl -u scorecast -f
```

Check the service status:

```bash
sudo systemctl status scorecast
```

Restart ScoreCast:

```bash
sudo systemctl restart scorecast
```

Restart the updater service manually:

```bash
sudo systemctl start scorecast-update
```

---

# Sports Bet Tracker

ScoreCast can track sports bets you already placed. It is not a sportsbook: there
are no deposits, withdrawals, or bet submissions.

Open **Bets** in the dashboard (signed in). Add a single or a parlay, pick a
league and game, then a player/market ScoreCast can actually see in its APIs.

## Supported leagues and markets

Tracked from existing ScoreCast data sources:

- **NFL / CFB** (ESPN scoreboard + game summary box score): passing/rushing/receiving
  yards and TDs, receptions, completions/attempts/INTs, rush+rec yards, anytime
  TD as rush+rec TDs, moneyline, spread, game total, team total.
- **NBA** (ESPN): points, rebounds, assists, threes, steals, blocks, turnovers,
  P+R+A combos, moneyline, spread, totals.
- **NHL** (ESPN): goals, assists, points, shots, saves, moneyline, spread, totals.
- **MLB** (MLB Stats API live feed / box score): hits, total bases, HR, runs, RBI,
  batter walks/Ks, pitcher Ks/walks/hits allowed, moneyline, spread, totals.

If a market cannot be read from those feeds, it is not offered. Lines and odds
are entered by you. ESPN game-center odds are not copied onto the slip.

## How tracking works

On each sports refresh, ScoreCast batches open bets by league and event, fetches
one summary/box score per event, then updates every leg on that game. Missing
stats are never graded as a loss. Overs on counting stats can clinch live once
they clear the line. Unders wait for a final (or go dead if the over already
cashed). Parlays lose if any leg loses; pushes/voids drop that leg instead of
counting as a win.

You can mark won/lost/push/void yourself if a sportsbook grades a weird market
differently. Manual grades are stored separately from automatic ones.

## Analytics and labels

Record, hit rate, net, and ROI use only bets that have the required fields.
Net/ROI ignore slips without stake+odds rather than treating them as $0.
Labels such as Money Player or No-Go need at least five settled results in that
bucket and describe *your* history, not whether a player is good.

## ScoreCast Estimate

Live hit chance, when shown, is a ScoreCast Estimate. It uses the player's
cached game log, current stat, and remaining game fraction, then a simple
normal remaining-production model. It is not a sportsbook probability.
Same-game parlays do not get a multiplied joint probability.

## LED board

Settings on the Add Bet page:

- Show open bets on the ticker
- Brief HIT / WON notices (never override Alerts or Focus)

## Storage

Bets live in `/var/lib/scorecast/bets.sqlite` (or `$SCORECAST_CONFIG_DIR`).
Existing ScoreCast installs create an empty database on first launch.

---

# APIs Used

## Sports

- MLB Stats API
- ESPN APIs
- NHL API

---

# License

MIT License
