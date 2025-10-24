# Raspberry Pi LCD Printer Dashboard

A tiny dashboard for a Raspberry Pi Zero with a 3.5" 480x320 LCD that shows printer server status.

CUPS service/printer status, queued jobs, Wi‑Fi IP, CPU, temperature etc.

<img src="https://github.com/user-attachments/assets/fb9e1e83-6f56-4e21-9288-577755bf6fb8" width="500px">

## Having trouble getting LCD output?

"Light" OS version didn't work for me. Try installing "Full". Then you can switch to boot to console.

## Dependencies

On Raspberry Pi OS/Debian:

```zsh
sudo apt update
sudo apt install -y python3 python3-pip fonts-dejavu-core cups-client # lpstat
# Optional for direct framebuffer drawing
sudo apt install -y python3-pygame
# Optional if you prefer PNG + console viewer
sudo apt install -y fbi

pip3 install --break-system-packages -r requirements.txt
```

If your system python/pip doesn’t use `--break-system-packages`, omit it.

## How to run

- PNG output (default):

```zsh
python3 dashboard_poc.py
# Image will be written to ./build/dashboard.png
```

- Direct to framebuffer with pygame (typical for 3.5" SPI LCDs on /dev/fb1):

```zsh
cd /src/print
DISPLAY_MODE=pygame FBDEV=/dev/fb1 python3 dashboard_poc.py
```

## Autostart with systemd

Install the provided unit and enable at boot:

```zsh
sudo cp service/lcd-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lcd-dashboard.service
```

If your framebuffer device differs, edit `Environment=FBDEV=/dev/fb1` in the unit file.

## Configuration

Environment variables:
- WIDTH / HEIGHT: Override display dimensions (defaults 480×320)
- OUTPUT_PATH: PNG path, default `./build/dashboard.png`
- DISPLAY_MODE: `png` (default) or `pygame`
- FBDEV: Framebuffer device (default `/dev/fb1`)
- REFRESH_SEC: Seconds between refreshes (default `1.0`)
- PRINTER: Filter queue size to a specific printer name
