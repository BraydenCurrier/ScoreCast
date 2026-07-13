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
```

---

## 2. Install Git

```bash
sudo apt install git -y
```

---

## 3. Install Python dependencies

```bash
sudo apt install \
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
ca-certificates \
-y
```

---

## 4. Clone ScoreCast

```bash
git clone https://github.com/BraydenCurrier/ScoreCast.git
cd ScoreCast
```

---

## 5. Create a virtual environment

```bash
python3 -m venv venv
```

Activate it:

```bash
source venv/bin/activate
```

---

## 6. Install Python packages

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 7. Install the RGB Matrix library

```bash
git clone https://github.com/hzeller/rpi-rgb-led-matrix.git

cd rpi-rgb-led-matrix

make build-python

sudo make install-python

cd ..
```

---

## 8. Run ScoreCast

```bash
sudo ./venv/bin/python src/main.py
```

The web dashboard will be available at:

```
http://<raspberry-pi-ip>:8080
```

---

# Run Automatically on Boot

Create a systemd service:

```bash
sudo nano /etc/systemd/system/scorecast.service
```

Paste:

```ini
[Unit]
Description=ScoreCast LED Sports Ticker
After=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/ScoreCast
ExecStart=/home/pi/ScoreCast/venv/bin/python /home/pi/ScoreCast/src/main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable scorecast
sudo systemctl start scorecast
```

View logs:

```bash
sudo journalctl -u scorecast -f
```

---

# Configuration

Everything can be configured from the web dashboard.

Current settings include:

- Game order
- Hidden games
- Brightness
- Scroll speed
- Refresh interval
- Betting odds
- News feeds

---

# APIs Used

## Sports

- MLB Stats API
- ESPN APIs
- NHL API

---

# License

MIT License
