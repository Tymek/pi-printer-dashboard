#!/usr/bin/env python3
"""
Renders a 480x320 image showing only the CUPS print queue size.

Environment variables (optional):
- OUTPUT_PATH: Path to write the PNG (default: ./build/dashboard.png)
- DISPLAY_MODE: 'png' (default) or 'pygame'
- FBDEV: Framebuffer device for pygame (default: /dev/fb1)
- WIDTH/HEIGHT: Override display size (defaults 480x320)
- PRINTER: Limit queue size to a specific printer name

Dependencies: Pillow (PIL). Pygame optional.
"""

import os
import time
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import atexit


# --- Config ---
WIDTH = int(os.environ.get("WIDTH", "480"))
HEIGHT = int(os.environ.get("HEIGHT", "320"))
OUTPUT_PATH = Path(os.environ.get("OUTPUT_PATH", "./build/dashboard.png")).resolve()
DISPLAY_MODE = os.environ.get("DISPLAY_MODE", "png").lower()
FBDEV = os.environ.get("FBDEV", "/dev/fb1")
PRINTER = os.environ.get("PRINTER")  # Optional: target a specific printer name
REFRESH_SEC = float(os.environ.get("REFRESH_SEC", "1.0"))
# Lighten collectors: configurable poll intervals (seconds)
CUPS_POLL_SEC = float(os.environ.get("CUPS_POLL_SEC", "2.0"))
NET_POLL_SEC = float(os.environ.get("NET_POLL_SEC", "30.0"))
TEMP_POLL_SEC = float(os.environ.get("TEMP_POLL_SEC", "2.0"))

BG = (12, 17, 27)  # deep navy
FG = (230, 235, 245)
ACCENT = (62, 136, 248)
WARN = (255, 179, 71)
ERR = (255, 99, 99)

PADDING = 16


def ensure_output_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Try to load a nice system font; fall back to PIL default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for fp in candidates:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size=size)
            except Exception:
                pass
    # Fallback
    return ImageFont.load_default()


def get_cups_queue_size(printer: Optional[str] = None) -> int:
    """Return the current CUPS queue size (optionally for a specific printer).

    Uses `lpstat -o` which lists jobs; we count the lines.
    Returns 0 on any error (e.g., CUPS not installed or service down).
    """
    cmd = ["lpstat", "-o"]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return 0
    except Exception:
        return 0

    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if printer:
        # Filter lines that begin with printer name (format: "printer-123 user ...")
        prefix = f"{printer}-"
        lines = [ln for ln in lines if ln.startswith(prefix)]
    return len(lines)


def get_cups_scheduler_status() -> str:
    # Prefer lpstat -r: "scheduler is running" or "not running"
    try:
        proc = subprocess.run(["lpstat", "-r"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        out = (proc.stdout or "").strip().lower()
        if "running" in out:
            return "running"
        if "not" in out:
            return "stopped"
    except Exception:
        pass
    # Fallback to systemctl if available
    try:
        proc = subprocess.run(["systemctl", "is-active", "cups"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return (proc.stdout or "unknown").strip()
    except Exception:
        return "unknown"


def get_ip_address() -> str:
    # hostname -I returns space-separated IPs; choose the first IPv4
    try:
        proc = subprocess.run(["hostname", "-I"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        ips = (proc.stdout or "").strip().split()
        for ip in ips:
            if ":" not in ip:  # ipv4 heuristic
                return ip
        return ips[0] if ips else ""
    except Exception:
        return ""


def get_cpu_temp_c() -> Optional[float]:
    # Try sysfs first
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            v = f.read().strip()
        return float(v) / 1000.0
    except Exception:
        pass
    # Fallback to vcgencmd
    try:
        proc = subprocess.run(["vcgencmd", "measure_temp"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        out = (proc.stdout or "").strip()
        # format: temp=45.2'C
        if out.startswith("temp=") and out.endswith("'C"):
            return float(out[5:-2])
    except Exception:
        pass
    return None


_HEADER_FONT_CACHE: dict[str, tuple[int, int, int]] = {}


def render_image(queue_size: int, cups_status: str, ip_addr: str, cpu_temp_c: Optional[float], cpu_usage_pct: Optional[float], printer_name: Optional[str], printer_state: Optional[str], current_job: Optional[str]) -> Image.Image:
    """Render a simple, clean dashboard image."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Fonts
    font_title = load_font(32)
    font_value = load_font(120)
    font_sub = load_font(20)
    font_big = load_font(56)

    # Header: printer name across full width
    header = printer_name or "Printer"
    if header in _HEADER_FONT_CACHE:
        cached_sz, hb_w, hb_h = _HEADER_FONT_CACHE[header]
        fh = load_font(cached_sz)
    else:
        header_font_size = 36
        while header_font_size > 18:
            fh = load_font(header_font_size)
            hb_w, hb_h = ImageDraw.Draw(Image.new("RGB", (1,1))).textbbox((0,0), header, font=fh)[2:]
            if hb_w <= WIDTH - 2*PADDING:
                break
            header_font_size -= 2
        _HEADER_FONT_CACHE[header] = (header_font_size, hb_w, hb_h)
    draw.text(((WIDTH - hb_w)//2, PADDING), header, font=fh, fill=FG)

    # Small status lines under the title
    info_y = PADDING + hb_h + 12
    cpu_line = "CPU: "
    if cpu_temp_c is not None:
        cpu_line += f"{cpu_temp_c:.1f}°C "
    else:
        cpu_line += "- "
    cpu_line += f"{cpu_usage_pct:.0f}%" if cpu_usage_pct is not None else "-%"
    info_lines = [
        f"CUPS: {cups_status}",
        f"IP: {ip_addr or '-'}",
        cpu_line,
    ]
    for i, line in enumerate(info_lines):
        draw.text((PADDING, info_y + i * 22), line, font=font_sub, fill=(180, 195, 210))

    # Right column: printer panel
    right_x = WIDTH // 2 + PADDING
    y = info_y
    state = (printer_state or "unknown").lower()
    state_color = ACCENT if state == "idle" else (WARN if state.startswith("printing") else (200, 120, 140))
    # Big state word
    st_w, st_h = draw.textbbox((0,0), state, font=font_big)[2:]
    draw.text((right_x, y), state, font=font_big, fill=state_color)
    y += st_h + 8
    if current_job:
        draw.text((right_x, y), f"Current: {current_job}", font=font_sub, fill=(180, 195, 210))
        y += 24
    # Big queue number
    q_label = "Queue"
    draw.text((right_x, y), q_label, font=font_sub, fill=(160, 175, 190))
    y += 22
    q_text = str(queue_size)
    q_w, q_h = draw.textbbox((0,0), q_text, font=font_big)[2:]
    draw.text((right_x, y), q_text, font=font_big, fill=FG)

    # Footer: heartbeat + timestamp
    now = datetime.now().strftime("%H:%M:%S")
    footer = f"Updated {now}"
    ft_w, ft_h = draw.textbbox((0, 0), footer, font=font_sub)[2:]
    draw.text((WIDTH - PADDING - ft_w, HEIGHT - PADDING - ft_h), footer, font=font_sub, fill=(140, 150, 165))
    # Heartbeat dot that flips color each refresh (use seconds parity)
    hb_on = (int(datetime.now().strftime('%S')) % 2) == 0
    hb_color = ACCENT if hb_on else (140, 150, 165)
    r = 6
    cx, cy = PADDING + r, HEIGHT - PADDING - r
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=hb_color)

    return img


def try_display_with_pygame(img: Image.Image) -> bool:
    """Attempt to display directly using pygame on framebuffer. Returns True if successful."""
    # Lazy import
    try:
        import pygame
        os.putenv("SDL_VIDEODRIVER", "fbcon")
        os.putenv("SDL_FBDEV", FBDEV)
        pygame.display.init()
        screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.mouse.set_visible(False)

        mode = img.mode
        data = img.tobytes()
        surface = pygame.image.fromstring(data, img.size, mode)
        screen.blit(surface, (0, 0))
        pygame.display.update()
        return True
    except Exception:
        # Surface/pygame errors can be silent under systemd; surface to stderr so journalctl captures it
        try:
            import traceback
            traceback.print_exc()
        except Exception:
            pass
        return False


def _read_fb_virtual_size(dev: str) -> Optional[tuple[int, int]]:
    try:
        name = os.path.basename(dev)
        p = f"/sys/class/graphics/{name}/virtual_size"
        with open(p, "r") as f:
            txt = f.read().strip()
        w, h = txt.split(",")
        return int(w), int(h)
    except Exception:
        return None


def _read_fb_bpp(dev: str) -> Optional[int]:
    try:
        name = os.path.basename(dev)
        p = f"/sys/class/graphics/{name}/bits_per_pixel"
        with open(p, "r") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _rgb_to_rgb565_bytes(img: Image.Image) -> bytes:
    rgb = img.convert("RGB")
    data = rgb.tobytes()
    out = bytearray(len(data) // 3 * 2)
    j = 0
    for i in range(0, len(data), 3):
        r = data[i]
        g = data[i + 1]
        b = data[i + 2]
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[j] = v & 0xFF
        out[j + 1] = (v >> 8) & 0xFF
        j += 2
    return bytes(out)


def get_printer_state_and_current(printer: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (printer_name, state, current_job_desc).
    - printer_name: the resolved printer name
    - state: 'idle', 'printing', 'stopped', ... (lowercase if parsed)
    - current_job_desc: a short 'user: title' from the first job in queue
    """
    resolved = printer
    state: Optional[str] = None
    current: Optional[str] = None
    def _parse_state(text: str) -> Optional[str]:
        low = text.lower()
        # Common forms:
        # 'printer NAME is idle.  enabled since ...'
        # 'printer NAME is printing ...'
        # 'printer NAME status is idle. enabled ...'
        for key in ("status is", " is "):
            if key in low:
                seg = low.split(key, 1)[1]
                # take up to period or double-space
                part = seg.split(".", 1)[0]
                part = part.split("  ", 1)[0]
                return part.strip()
        return None

    try:
        # lpstat -p shows printers and states
        proc = subprocess.run(["lpstat", "-p"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        out = proc.stdout or ""
        for line in out.splitlines():
            line = line.strip()
            if not line.lower().startswith("printer "):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            name = parts[1]
            if printer and name != printer:
                continue
            resolved = name
            st = _parse_state(line)
            if st:
                state = st
            break
    except Exception:
        pass

    try:
        # Grab first job for this printer (or any if printer unspecified)
        proc = subprocess.run(["lpstat", "-o"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        out = proc.stdout or ""
        for line in out.splitlines():
            line = line.strip()
            # Format: 'printer-123  user  12345   ...  title'
            if not line:
                continue
            job_pr = line.split()[0]
            if "-" not in job_pr:
                continue
            pr_name = job_pr.rsplit("-", 1)[0]
            if printer and pr_name != printer:
                continue
            # Extract user and title best-effort
            parts = line.split()
            user = parts[1] if len(parts) > 1 else "?"
            # Title may be at the end; take last token(s) after some columns
            title = line
            # Try to find after '  ' double spaces which often separate header from title
            if "  " in line:
                title = line.split("  ", 1)[-1].strip()
            current = f"{user}: {title[:26]}"  # keep short
            break
    except Exception:
        pass

    return resolved, (state.lower() if isinstance(state, str) else state), current


def clear_display():
    """Clear the display on exit (best-effort)."""
    try:
        if DISPLAY_MODE == "pygame":
            import pygame
            os.putenv("SDL_VIDEODRIVER", "fbcon")
            os.putenv("SDL_FBDEV", FBDEV)
            pygame.display.init()
            screen = pygame.display.set_mode((WIDTH, HEIGHT))
            screen.fill((0, 0, 0))
            pygame.display.update()
            pygame.display.quit()
        elif DISPLAY_MODE == "fb" and os.path.exists(FBDEV):
            black = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
            try_display_with_fb(black)
    except Exception:
        pass

# Clear the display on any normal interpreter exit as well
atexit.register(clear_display)


def try_display_with_fb(img: Image.Image) -> bool:
    dev = FBDEV
    if not os.path.exists(dev):
        return False
    try:
        target_size = _read_fb_virtual_size(dev) or (WIDTH, HEIGHT)
        bpp = _read_fb_bpp(dev) or 16
        w, h = target_size
        if img.size != (w, h):
            img = img.resize((w, h), Image.LANCZOS)

        if bpp == 16:
            raw = _rgb_to_rgb565_bytes(img)
            line_len = w * 2
        elif bpp in (24, 32):
            raw = img.convert("RGB").tobytes()
            line_len = w * 3
        else:
            return False

        with open(dev, "rb+") as f:
            for y in range(h):
                start = y * line_len
                end = start + line_len
                f.seek(y * line_len)
                f.write(raw[start:end])
            try:
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                pass
        return True
    except Exception:
        # Report exceptions to stderr so they appear in the journal
        try:
            import traceback
            traceback.print_exc()
        except Exception:
            pass
        return False


def _read_cpu_idle_total() -> Optional[Tuple[int, int]]:
    try:
        with open("/proc/stat", "r") as f:
            first = f.readline()
        parts = first.strip().split()
        if parts[0] != "cpu":
            return None
        vals = [int(x) for x in parts[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        total = sum(vals)
        return idle, total
    except Exception:
        return None


def main():
    ensure_output_dir(OUTPUT_PATH)
    last_drawn = -1
    prev_cpu: Optional[Tuple[int, int]] = None
    # Cached values with timestamps
    last_cups_t = 0.0
    cups_status_cache = "unknown"
    printer_name_cache: Optional[str] = None
    printer_state_cache: Optional[str] = None
    current_job_cache: Optional[str] = None
    last_net_t = 0.0
    ip_cache = ""
    last_temp_t = 0.0
    temp_cache: Optional[float] = None

    while True:
        try:
            now = time.time()
            if now - last_cups_t >= CUPS_POLL_SEC:
                cups_status_cache = get_cups_scheduler_status()
                printer_name_cache, printer_state_cache, current_job_cache = get_printer_state_and_current(PRINTER)
                last_cups_t = now
            cups_status = cups_status_cache
            printer_name = printer_name_cache
            printer_state = printer_state_cache
            current_job = current_job_cache
            # Queue size: prefer resolved printer specific count
            q_target = printer_name or PRINTER
            qsize = get_cups_queue_size(q_target)
            if now - last_net_t >= NET_POLL_SEC:
                ip_cache = get_ip_address()
                last_net_t = now
            ip_addr = ip_cache
            if now - last_temp_t >= TEMP_POLL_SEC:
                temp_cache = get_cpu_temp_c()
                last_temp_t = now
            cpu_temp_c = temp_cache
            # CPU usage
            cpu_usage_pct: Optional[float] = None
            cur_cpu = _read_cpu_idle_total()
            if prev_cpu and cur_cpu:
                idle_d = cur_cpu[0] - prev_cpu[0]
                total_d = cur_cpu[1] - prev_cpu[1]
                if total_d > 0:
                    cpu_usage_pct = max(0.0, min(100.0, (1.0 - (idle_d / total_d)) * 100.0))
            prev_cpu = cur_cpu or prev_cpu

            # Derive a friendlier state: printing if a current job exists; queued if jobs pending; else parsed state
            derived_state = (printer_state or "unknown").lower()
            if current_job:
                derived_state = "printing"
            elif qsize and qsize > 0:
                derived_state = "queued"

            # Only redraw if queue size changed or on a cadence; keep it simple: always redraw.
            img = render_image(qsize, cups_status, ip_addr, cpu_temp_c, cpu_usage_pct, printer_name, derived_state, current_job)

            if DISPLAY_MODE == "pygame":
                if not try_display_with_pygame(img):
                    img.save(OUTPUT_PATH)
            elif DISPLAY_MODE == "fb":
                if not try_display_with_fb(img):
                    img.save(OUTPUT_PATH)
            else:
                img.save(OUTPUT_PATH)

            last_drawn = qsize

            time.sleep(REFRESH_SEC)
        except KeyboardInterrupt:
            clear_display()
            break
        except Exception:
            # Print tracebacks to stderr so systemd/journalctl records why the loop failed.
            try:
                import traceback
                traceback.print_exc()
            except Exception:
                pass
            # Don't crash the loop if any collector/render error occurs
            time.sleep(REFRESH_SEC)


if __name__ == "__main__":
    main()
