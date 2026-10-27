"""Background threads, shared state, camera, DHT, GPS, and GPIO services."""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import cv2
import numpy as np

from config import Config

log = logging.getLogger(__name__)


@dataclass
class AppState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    events: deque[str] = field(default_factory=lambda: deque(maxlen=80))
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    board_temp_c: Optional[float] = None
    dht_ok: bool = False
    temperature_source: str = "none"
    dht_error: str = ""
    motion_score: float = 0.0
    last_motion_ts: float = field(default_factory=time.time)
    last_ir_motion_ts: float = 0.0
    inactivity_alert: bool = False
    ir_motion: bool = True
    red_led: bool = False
    blue_led: bool = False
    blue_led_until_ts: float = 0.0
    inactivity_buzzer_until_ts: float = 0.0
    emergency_active: bool = False
    camera_ok: bool = False
    camera_error: str = ""
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    gps_status: str = ""
    gps_sats: int = 0
    last_jpeg: bytes = b""
    servo_base_deg: float = 90.0
    servo_top_deg: float = 90.0

    def add_event(self, line: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.events.appendleft(f"[{ts}] {line}")

    def heartbeat_snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "red_led": self.red_led,
                "emergency_active": self.emergency_active,
                "blue_led": self.blue_led,
                "inactivity_alert": self.inactivity_alert,
                "events": list(self.events)[:40],
                "temperature_c": self.temperature_c,
                "humidity_pct": self.humidity_pct,
                "board_temp_c": self.board_temp_c,
                "dht_ok": self.dht_ok,
                "temperature_source": self.temperature_source,
                "dht_error": self.dht_error,
                "gps_lat": self.gps_lat,
                "gps_lon": self.gps_lon,
                "gps_status": self.gps_status,
                "gps_sats": self.gps_sats,
                "motion_score": round(self.motion_score, 3),
                "ir_motion": self.ir_motion,
            }

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            se = getattr(Config, "SERVO_ENABLED", False)
            sb = float(self.servo_base_deg)
            st = float(self.servo_top_deg)
            return {
                "temperature_c": self.temperature_c,
                "humidity_pct": self.humidity_pct,
                "board_temp_c": self.board_temp_c,
                "dht_ok": self.dht_ok,
                "temperature_source": self.temperature_source,
                "dht_error": self.dht_error,
                "motion_score": round(self.motion_score, 3),
                "last_ir_motion_ts": self.last_ir_motion_ts,
                "inactivity_alert": self.inactivity_alert,
                "emergency_active": self.emergency_active,
                "ir_motion": self.ir_motion,
                "red_led": self.red_led,
                "blue_led": self.blue_led,
                "blue_led_until_ts": self.blue_led_until_ts,
                "inactivity_buzzer_until_ts": self.inactivity_buzzer_until_ts,
                "camera_ok": self.camera_ok,
                "camera_error": self.camera_error,
                "gps_lat": self.gps_lat,
                "gps_lon": self.gps_lon,
                "gps_status": self.gps_status,
                "gps_sats": self.gps_sats,
                "servo_base_deg": int(round(max(0.0, min(180.0, sb)))),
                "servo_top_deg": int(round(max(0.0, min(180.0, st)))),
                "servo_enabled": bool(se),
                "servo_ui_only": False,
                "servo_step_deg": int(getattr(Config, "SERVO_STEP_DEGREES", 15)),
                "events": list(self.events),
            }


STATE = AppState()
_hw: Any = None
_cfg: Optional[type] = None
_threads_started = False
_stop_cam = threading.Event()
_stop_misc = threading.Event()


def _notify(body: str, key: str) -> None:
    if _cfg is None:
        return
    from .notifier import dispatch_alert

    for line in dispatch_alert(body, key, _cfg):
        STATE.add_event(line)


def _notify_async(body: str, key: str) -> None:
    def run() -> None:
        try:
            _notify(body, key)
        except Exception:
            log.exception("Asynchronous notification failed: %s", key)

    threading.Thread(target=run, daemon=True, name=f"notify-{key}").start()


def _camera_stream_size() -> tuple[int, int]:
    if _cfg is None:
        return 640, 480
    w = int(getattr(_cfg, "CAMERA_STREAM_WIDTH", 640))
    h = int(getattr(_cfg, "CAMERA_STREAM_HEIGHT", 480))
    return max(160, min(1920, w)), max(120, min(1440, h))


def _camera_loop_sleep_sec() -> float:
    if _cfg is None:
        return 0.125
    fps = float(getattr(_cfg, "CAMERA_PREVIEW_FPS", 8) or 8)
    fps = max(1.0, min(30.0, fps))
    return 1.0 / fps


def _jpeg_encode_params() -> list[int]:
    q = int(getattr(_cfg, "CAMERA_JPEG_QUALITY", 65) or 65) if _cfg else 65
    q = max(40, min(95, q))
    return [int(cv2.IMWRITE_JPEG_QUALITY), q]


def _soc_temp_c() -> Optional[float]:
    try:
        out = subprocess.check_output(
            ["/usr/bin/vcgencmd", "measure_temp"], text=True, timeout=2
        )
        m = re.search(r"temp=([\d.]+)", out)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def _inactivity_led_seconds() -> float:
    try:
        s = float(getattr(_cfg, "INACTIVITY_LED_SECONDS", 30) or 30)
    except (TypeError, ValueError):
        s = 30.0
    return max(1.0, min(300.0, s))


def _inactivity_buzzer_seconds() -> float:
    try:
        s = float(getattr(_cfg, "INACTIVITY_BUZZER_SECONDS", 5) or 5)
    except (TypeError, ValueError):
        s = 5.0
    return max(0.5, min(120.0, s))


def _ir_presence_hold_seconds() -> float:
    try:
        s = float(getattr(_cfg, "IR_PRESENCE_HOLD_SECONDS", 180) or 180)
    except (TypeError, ValueError):
        s = 180.0
    return max(5.0, min(3600.0, s))


def _expire_blue_led_if_needed(now: float) -> None:
    global _hw
    if _cfg is None:
        return
    should_off = False
    should_buzzer_off = False
    with STATE.lock:
        if (
            STATE.blue_led
            and STATE.blue_led_until_ts > 0
            and now >= STATE.blue_led_until_ts
        ):
            should_off = True
            STATE.blue_led = False
            STATE.blue_led_until_ts = 0.0
        if (
            STATE.inactivity_buzzer_until_ts > 0
            and now >= STATE.inactivity_buzzer_until_ts
            and not STATE.emergency_active
        ):
            should_buzzer_off = True
            STATE.inactivity_buzzer_until_ts = 0.0
    if should_off and _hw:
        _hw.set_blue_led(False)
    if should_buzzer_off and _hw:
        _hw.set_buzzer(False)
    if should_off:
        STATE.add_event("Inactivity alert: the blue LED turned off after its timer expired")
    if should_buzzer_off:
        STATE.add_event("Inactivity alert: the buzzer stopped after its timed pulse")


def _camera_motion_inactivity_pass(motion: bool, now: float) -> None:
    global _cfg, _hw
    if _cfg is None:
        return
    motion_cleared = False
    ir_cleared = False
    buzzer_off_motion = False
    buzzer_off_ir = False
    became_inactive = False
    buzzer_on_inactive = False
    with STATE.lock:
        if motion:
            STATE.last_motion_ts = now
            if STATE.inactivity_alert:
                STATE.inactivity_alert = False
                STATE.blue_led = False
                STATE.blue_led_until_ts = 0.0
                STATE.inactivity_buzzer_until_ts = 0.0
                motion_cleared = True
                buzzer_off_motion = not STATE.emergency_active

        inactive_for = now - STATE.last_motion_ts
        ir_seen_recently = (
            now - STATE.last_ir_motion_ts <= _ir_presence_hold_seconds()
        )
        became_inactive = (
            ir_seen_recently
            and inactive_for >= _cfg.INACTIVITY_SECONDS
            and not STATE.inactivity_alert
        )

        if (not ir_seen_recently) and STATE.inactivity_alert:
            STATE.inactivity_alert = False
            STATE.blue_led = False
            STATE.blue_led_until_ts = 0.0
            STATE.inactivity_buzzer_until_ts = 0.0
            ir_cleared = True
            buzzer_off_ir = not STATE.emergency_active

        if became_inactive:
            STATE.inactivity_alert = True
            STATE.blue_led = True
            STATE.blue_led_until_ts = now + _inactivity_led_seconds()
            STATE.inactivity_buzzer_until_ts = now + _inactivity_buzzer_seconds()
            buzzer_on_inactive = not STATE.emergency_active

    if motion_cleared and _hw:
        _hw.set_blue_led(False)
        if buzzer_off_motion:
            _hw.set_buzzer(False)
    if ir_cleared and _hw:
        _hw.set_blue_led(False)
        if buzzer_off_ir:
            _hw.set_buzzer(False)

    if motion_cleared:
        STATE.add_event("Motion detected; prolonged-inactivity alert cleared")
    if ir_cleared:
        STATE.add_event("No person detected by the infrared sensor; inactivity alert cleared")

    if became_inactive:
        if _hw:
            _hw.set_blue_led(True)
            if buzzer_on_inactive:
                _hw.set_buzzer(True)
        STATE.add_event("Prolonged inactivity detected — blue LED activated and notification attempted")
        _notify_async("[Care Alert] Prolonged inactivity or minimal camera movement detected. Please check in.", "inactivity")


def _motion_score_and_detect(prev_gray, gray) -> tuple[float, bool]:
    global _cfg
    if _cfg is None:
        return 0.0, False
    try:
        scale = int(getattr(_cfg, "MOTION_DOWNSCALE", 4) or 4)
    except (TypeError, ValueError):
        scale = 4
    scale = max(1, min(8, scale))
    h, w = gray.shape[:2]
    tw = max(64, w // scale)
    th = max(48, h // scale)
    p = cv2.resize(prev_gray, (tw, th), interpolation=cv2.INTER_AREA)
    g = cv2.resize(gray, (tw, th), interpolation=cv2.INTER_AREA)
    diff = cv2.absdiff(p, g)
    try:
        pix_thr = int(getattr(_cfg, "MOTION_PIXEL_THRESHOLD", 22))
    except (TypeError, ValueError):
        pix_thr = 22
    pix_thr = max(5, min(80, pix_thr))
    frac = float((diff > pix_thr).mean())
    score_pct = round(frac * 100.0, 4)
    try:
        thr_pct = float(getattr(_cfg, "MOTION_THRESHOLD", 1.2))
    except (TypeError, ValueError):
        thr_pct = 1.2
    thr_pct = max(0.05, min(50.0, thr_pct))
    motion = score_pct >= thr_pct
    return score_pct, motion


def _nmea_to_decimal(raw: str, hemi: str) -> Optional[float]:
    s = (raw or "").strip()
    h = (hemi or "").strip().upper()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    deg = int(v // 100)
    minute = v - deg * 100
    out = deg + minute / 60.0
    if h in ("S", "W"):
        out = -out
    return round(out, 6)


def _parse_nmea_latlon(line: str) -> tuple[Optional[float], Optional[float]]:
    parts = line.strip().split(",")
    typ = parts[0] if parts else ""
    if typ in ("$GPRMC", "$GNRMC") and len(parts) >= 7:
        if parts[2] != "A":
            return None, None
        lat = _nmea_to_decimal(parts[3], parts[4])
        lon = _nmea_to_decimal(parts[5], parts[6])
        return lat, lon
    if typ in ("$GPGGA", "$GNGGA") and len(parts) >= 7:
        try:
            fixq = int(parts[6] or "0")
        except ValueError:
            fixq = 0
        if fixq <= 0:
            return None, None
        lat = _nmea_to_decimal(parts[2], parts[3])
        lon = _nmea_to_decimal(parts[4], parts[5])
        return lat, lon
    return None, None


def _parse_gga_sats(line: str) -> tuple[Optional[int], Optional[int]]:
    parts = line.strip().split(",")
    if len(parts) < 8 or parts[0] not in ("$GPGGA", "$GNGGA"):
        return None, None
    try:
        fixq = int(parts[6] or "0")
        sats = int(parts[7] or "0")
        return fixq, sats
    except ValueError:
        return None, None


def _dht_loop(stop: threading.Event) -> None:
    from . import hardware as hwmod

    while not stop.is_set():
        if _cfg is None:
            time.sleep(2)
            continue
        gpio = int(_cfg.DHT_GPIO)
        t, h, err = hwmod.read_dht(gpio, _cfg.DHT_TYPE)
        bt = _soc_temp_c()
        with STATE.lock:
            STATE.board_temp_c = bt
            if t is not None and h is not None:
                STATE.temperature_c = round(t, 1)
                STATE.humidity_pct = round(h, 1)
                STATE.dht_ok = True
                STATE.temperature_source = "dht"
                STATE.dht_error = ""
            elif t is not None:
                STATE.temperature_c = round(t, 1)
                STATE.humidity_pct = None
                STATE.dht_ok = False
                STATE.temperature_source = "dht_partial"
                STATE.dht_error = err or "Temperature only"
            elif h is not None:
                STATE.temperature_c = None
                STATE.humidity_pct = round(h, 1)
                STATE.dht_ok = False
                STATE.temperature_source = "dht_partial"
                STATE.dht_error = err or "Humidity only"
            else:
                STATE.temperature_c = None
                STATE.humidity_pct = None
                STATE.dht_ok = False
                STATE.temperature_source = "none"
                STATE.dht_error = err or "No DHT reading"
        try:
            interval = float(getattr(_cfg, "DHT_POLL_INTERVAL_SEC", 2.0) or 2.0)
        except (TypeError, ValueError):
            interval = 2.0
        interval = max(1.0, min(60.0, interval))
        stop.wait(interval)


def _gps_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        if _cfg is None:
            time.sleep(2)
            continue
        path = getattr(_cfg, "GPS_SERIAL", "/dev/serial0")
        baud = int(getattr(_cfg, "GPS_BAUD", 9600))
        try:
            import serial

            with serial.Serial(path, baud, timeout=1) as ser:
                with STATE.lock:
                    STATE.gps_status = "Searching for satellites…"
                while not stop.is_set():
                    line = ser.readline().decode("ascii", errors="ignore")
                    lat, lon = _parse_nmea_latlon(line)
                    fq, sats = _parse_gga_sats(line)
                    with STATE.lock:
                        if lat is not None and lon is not None:
                            STATE.gps_lat = lat
                            STATE.gps_lon = lon
                            STATE.gps_status = "Position acquired"
                        if sats is not None:
                            STATE.gps_sats = sats
        except Exception as e:
            msg = str(e)
            hint = ""
            if "Permission denied" in msg or "Errno 13" in msg:
                hint = (
                    " — Fix: add SupplementaryGroups=dialout gpio video under [Service] "
                    "in /etc/systemd/system/elder-car.service, then run "
                    "sudo systemctl daemon-reload && sudo systemctl restart elder-car"
                )
            with STATE.lock:
                STATE.gps_status = f"Serial-port error: {e}{hint}"
            stop.wait(5)


def _gpio_red_button_loop(stop: threading.Event) -> None:
    global _hw
    if _hw is None:
        return
    # Initialize from the actual power-on level so a steady LOW/HIGH is not mistaken for a button transition.
    last = _hw.read_red_button()
    debounce = 0.0
    while not stop.is_set():
        pressed = _hw.read_red_button()
        now = time.time()
        if pressed and not last and (now - debounce) > 0.35:
            debounce = now
            with STATE.lock:
                if not STATE.emergency_active:
                    STATE.emergency_active = True
                    STATE.red_led = True
                    toggle_on = True
                else:
                    STATE.emergency_active = False
                    STATE.red_led = False
                    toggle_on = False
            if toggle_on:
                _hw.set_red_led(True)
                _hw.set_buzzer(True)
                STATE.add_event("Red button: emergency alert activated (red LED on)")
                _notify_async("[Emergency Alert] The red assistance button was pressed. Please respond immediately.", "emergency")
            else:
                _hw.set_red_led(False)
                _hw.set_buzzer(False)
                STATE.add_event("Red button: emergency alert cleared (red LED off)")
                _notify_async("[Alert Cleared] The red button was pressed again and the emergency alert was canceled.", "mistake")
        last = pressed
        stop.wait(0.05)


def _open_cv_capture() -> tuple[Any, Optional[int]]:
    order = []
    if _cfg:
        if _cfg.CAMERA_INDEX not in _cfg.CAMERA_TRY_INDICES:
            order.append(_cfg.CAMERA_INDEX)
        order.extend(i for i in _cfg.CAMERA_TRY_INDICES if i not in order)
    else:
        order = [0]
    cap = None
    used = None
    for idx in order:
        c = cv2.VideoCapture(idx)
        if c.isOpened():
            cap = c
            used = idx
            break
        c.release()
    return cap, used


def _camera_loop(stop: threading.Event) -> None:
    global _cfg, _hw
    w, h = _camera_stream_size()
    prev_gray = None

    def process_frame(frame_bgr: np.ndarray) -> None:
        nonlocal prev_gray
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        now = time.time()
        ir_active = True
        if _hw is not None:
            try:
                ir_active = _hw.read_ir_motion()
            except Exception:
                ir_active = True

        if prev_gray is None:
            prev_gray = gray
            score, motion = 0.0, False
        else:
            score, motion = _motion_score_and_detect(prev_gray, gray)
            prev_gray = gray

        with STATE.lock:
            STATE.camera_ok = True
            STATE.camera_error = ""
            STATE.motion_score = score
            STATE.ir_motion = ir_active
            if ir_active:
                STATE.last_ir_motion_ts = now

        _camera_motion_inactivity_pass(motion, now)
        _expire_blue_led_if_needed(now)

        ok_enc, buf = cv2.imencode(".jpg", frame_bgr, _jpeg_encode_params())
        if ok_enc:
            with STATE.lock:
                STATE.last_jpeg = buf.tobytes()

    use_pi = bool(_cfg and getattr(_cfg, "USE_PICAMERA2", True))
    if use_pi:
        try:
            from picamera2 import Picamera2  # type: ignore

            picam2 = Picamera2()
            cfg = picam2.create_preview_configuration(
                main={"size": (w, h), "format": "RGB888"}
            )
            picam2.configure(cfg)
            picam2.start()
            with STATE.lock:
                STATE.camera_error = ""
            while not stop.is_set():
                arr = picam2.capture_array()
                frame = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                process_frame(frame)
                time.sleep(_camera_loop_sleep_sec())
            picam2.stop()
            return
        except Exception as e:
            log.warning("Picamera2 unavailable; falling back to OpenCV: %s", e)
            with STATE.lock:
                STATE.camera_error = f"Picamera2 failed; trying OpenCV: {e}"

    cap, idx = _open_cv_capture()
    if cap is None or not cap.isOpened():
        with STATE.lock:
            STATE.camera_ok = False
            STATE.camera_error = "Unable to open the camera"
        while not stop.is_set():
            time.sleep(2)
        return

    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    except Exception:
        pass

    with STATE.lock:
        STATE.camera_error = "" if idx is None else f"OpenCV device {idx}"

    while not stop.is_set():
        ok, frame = cap.read()
        if not ok or frame is None:
            with STATE.lock:
                STATE.camera_ok = False
                STATE.camera_error = "Failed to read a camera frame"
            time.sleep(0.5)
            continue
        process_frame(frame)
        time.sleep(_camera_loop_sleep_sec())
    cap.release()


def set_servo_from_web(axis: str, angle: Optional[float], delta: Optional[float]) -> tuple[bool, str]:
    global _hw, _cfg
    if _cfg is None or not getattr(_cfg, "SERVO_ENABLED", False):
        return False, "Servos are disabled. Set SERVO_ENABLED=1 and restart the service."
    if _hw is None:
        return False, "GPIO is not initialized"
    axis = axis.strip().lower()
    if axis not in ("base", "top"):
        return False, "axis must be base or top"
    with STATE.lock:
        cur = STATE.servo_base_deg if axis == "base" else STATE.servo_top_deg
        if angle is not None:
            target = float(angle)
        elif delta is not None:
            target = cur + float(delta)
        else:
            return False, "angle or delta is required"
        target = max(0.0, min(180.0, target))
        if axis == "base":
            STATE.servo_base_deg = target
        else:
            STATE.servo_top_deg = target
    _hw.set_servo_angle(axis, target)
    return True, ""


def set_led_manual(color: str, on: bool) -> tuple[bool, str]:
    global _hw
    if _hw is None:
        return False, "GPIO is not initialized"
    c = color.strip().lower()
    if c not in ("red", "blue"):
        return False, "color must be red or blue"
    with STATE.lock:
        if c == "red":
            STATE.red_led = on
            STATE.emergency_active = on
        else:
            STATE.blue_led = on
    if c == "red":
        _hw.set_red_led(on)
        _hw.set_buzzer(on)
    else:
        _hw.set_blue_led(on)
    color_name = "red" if c == "red" else "blue"
    STATE.add_event(f"Web self-test: {color_name} LED {'on' if on else 'off'}")
    return True, ""


def start_background(app: Any) -> None:
    global _cfg, _hw, _threads_started  # noqa: PLW0603
    if _threads_started:
        return
    _threads_started = True
    _cfg = Config

    buzzer = Config.BUZZER_GPIO if Config.BUZZER_GPIO else None
    sb = Config.SERVO_BASE_GPIO if Config.SERVO_ENABLED else None
    st = Config.SERVO_TOP_GPIO if Config.SERVO_ENABLED else None

    from .hardware import Hardware

    _hw = Hardware(
        red_led=Config.RED_LED_GPIO,
        blue_led=Config.BLUE_LED_GPIO,
        red_button=Config.RED_BUTTON_GPIO,
        ir_motion=Config.IR_MOTION_GPIO,
        ir_active_high=Config.IR_ACTIVE_HIGH,
        red_button_active_high=Config.RED_BUTTON_ACTIVE_HIGH,
        led_active_low=Config.LED_ACTIVE_LOW,
        buzzer_gpio=int(buzzer) if buzzer else None,
        buzzer_active_low=Config.BUZZER_ACTIVE_LOW,
        servo_base_gpio=sb,
        servo_top_gpio=st,
    )

    threading.Thread(target=_camera_loop, args=(_stop_cam,), daemon=True, name="cam").start()
    threading.Thread(target=_dht_loop, args=(_stop_misc,), daemon=True, name="dht").start()
    threading.Thread(target=_gps_loop, args=(_stop_misc,), daemon=True, name="gps").start()
    threading.Thread(
        target=_gpio_red_button_loop, args=(_stop_misc,), daemon=True, name="btn"
    ).start()
    log.info("Background threads started")


def mjpeg_generator(boundary: bytes):
    stream_fps = float(getattr(Config, "VIDEO_STREAM_FPS", 8) or 8)
    stream_fps = max(1.0, min(30.0, stream_fps))
    period = 1.0 / stream_fps
    while True:
        t0 = time.time()
        with STATE.lock:
            jpg = STATE.last_jpeg
        if not jpg:
            time.sleep(0.05)
            continue
        yield (
            b"--"
            + boundary
            + b"\r\nContent-Type: image/jpeg\r\n\r\n"
            + jpg
            + b"\r\n"
        )
        dt = time.time() - t0
        if dt < period:
            time.sleep(period - dt)
