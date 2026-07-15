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

Flash **Raspberry Pi OS Lite (64-bit)** to your SD card using Raspberry Pi Imager.

After booting, update the Pi:

```bash
sudo apt update
sudo apt upgrade -y
sudo reboot
```

---

## 2. Install required packages

```bash
sudo apt install -y \
git \
python3 \
python3-pip \
python3-venv \
python3-dev \
build-essential \
libjpeg-dev \
zlib1g-dev \
libopenjp2-7-dev \
libtiff5-dev \
libatlas-base-dev \
libfreetype6-dev \
liblcms2-dev \
libwebp-dev \
libharfbuzz-dev \
libfribidi-dev \
libxcb1-dev \
libssl-dev \
ca-certificates
```
---

## 3. Clone ScoreCast

```bash
cd /opt
sudo git clone https://github.com/BraydenCurrier/ScoreCast.git scorecast
sudo chown -R $USER:$USER /opt/scorecast
cd /opt/scorecast
```

---

## 4. Create a virtual environment

```bash
python3 -m venv venv
```

Activate it:

```bash
source venv/bin/activate
```

---

## 5. Install Python packages

```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

---

## 6. Install the RGB Matrix library

```bash
cd /opt

git clone https://github.com/hzeller/rpi-rgb-led-matrix.git

cd rpi-rgb-led-matrix

make build-python

sudo make install-python

cd /opt/scorecast
```

---

## 7. Create the persistent settings directory

ScoreCast stores all user settings outside of the application so they survive updates and power loss.

```bash
sudo mkdir -p /var/lib/scorecast
sudo chown root:root /var/lib/scorecast
sudo chmod 700 /var/lib/scorecast
```

---

# 8. Install the systemd service

Create the service:

```bash
sudo nano /etc/systemd/system/scorecast.service
```

Paste:

```ini
[Unit]
Description=ScoreCast LED Sports Ticker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

User=root
Group=root

WorkingDirectory=/opt/scorecast

ExecStart=/opt/scorecast/venv/bin/python /opt/scorecast/src/main.py

Restart=always
RestartSec=3

StateDirectory=scorecast
StateDirectoryMode=0700
ReadWritePaths=/var/lib/scorecast

Environment=SCORECAST_CONFIG_DIR=/var/lib/scorecast
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable scorecast
sudo systemctl start scorecast
```

Verify it is running:

```bash
sudo systemctl status scorecast
```

View logs:

```bash
sudo journalctl -u scorecast -f
```

---

# 9. Open the Web Dashboard
Find your Pi's IP address:

```bash
hostname -I
```

Open:

```bash
http://<raspberry-pi-ip>:8080
```

Then you can add it to your homescreen as a bookmark to use it like an app.

Default Web App password:

```bash
ticker123
```

---

# Updating ScoreCast
ScoreCast includes a built-in updater.

When a new release is published on GitHub:
1. Open the web dashboard.
2. Click Check and Install Update.
3. Wait for the update to complete.
4. The Service will automatically restart.
5. Your setting are preserved.

---

# Configuration

Everything can be configured from the web dashboard.

Current settings include:

- Game order
- Hidden games
- Brightness
- Scroll speed
- Refresh interval

---

# APIs Used

## Sports

- MLB Stats API
- ESPN APIs
- NHL API

---

# License

MIT License
