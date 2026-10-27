"""
Application configuration.

The project-root `.env` file is loaded when this module is first imported (via python-dotenv; existing environment variables are not overwritten).

Selected environment variables:
  LED_ACTIVE_LOW=1 — many vehicle LED modules are active-low
  RED_LED_GPIO / BLUE_LED_GPIO / BUZZER_GPIO / RED_BUTTON_GPIO / IR_MOTION_GPIO
  RED_BUTTON_ACTIVE_HIGH=1 — use when a pressed button reads HIGH with an internal pull-down; the default assumes GND + pull-up
  DHT_GPIO / DHT_TYPE (DHT11|DHT22) — temperature and humidity use adafruit-circuitpython-dht (included in requirements)
  GPS_SERIAL / GPS_BAUD — add SupplementaryGroups=dialout to systemd when permissions fail; see extras/udev/99-elder-gps-serial.rules if /dev/ttyS0 remains root-only mode 600
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — Telegram alerts (can be enabled alongside SMS)
  TWILIO_* / ALERT_PHONE_E164 — SMS alerts
  WEB_BASIC_AUTH_USER / WEB_BASIC_AUTH_PASSWORD — enables web authentication when both values are set
  SERVO_ENABLED=1 — pan-tilt servos; SERVO_BASE_GPIO / SERVO_TOP_GPIO
  CAMERA_STREAM_WIDTH / HEIGHT — lower values reduce latency (for example, 480 x 360)
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
except ImportError:
    pass


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
    WEB_BASIC_AUTH_USER = os.environ.get("WEB_BASIC_AUTH_USER", "").strip()
    WEB_BASIC_AUTH_PASSWORD = os.environ.get("WEB_BASIC_AUTH_PASSWORD", "").strip()

    RED_LED_GPIO = int(os.environ.get("RED_LED_GPIO", "24"))
    BLUE_LED_GPIO = int(os.environ.get("BLUE_LED_GPIO", "17"))
    BUZZER_GPIO = os.environ.get("BUZZER_GPIO", "").strip()
    BUZZER_ACTIVE_LOW = os.environ.get("BUZZER_ACTIVE_LOW", "1").lower() in (
        "1",
        "true",
        "yes",
    )
    RED_BUTTON_GPIO = int(os.environ.get("RED_BUTTON_GPIO", "27"))
    RED_BUTTON_ACTIVE_HIGH = os.environ.get("RED_BUTTON_ACTIVE_HIGH", "").lower() in (
        "1",
        "true",
        "yes",
    )

    IR_MOTION_GPIO = int(os.environ.get("IR_MOTION_GPIO", "4"))
    IR_ACTIVE_HIGH = os.environ.get("IR_ACTIVE_HIGH", "1").lower() in (
        "1",
        "true",
        "yes",
    )
    IR_PRESENCE_HOLD_SECONDS = int(os.environ.get("IR_PRESENCE_HOLD_SECONDS", "180"))

    LED_ACTIVE_LOW = os.environ.get("LED_ACTIVE_LOW", "").lower() in (
        "1",
        "true",
        "yes",
    )

    DHT_GPIO = int(os.environ.get("DHT_GPIO", "18"))
    DHT_TYPE = os.environ.get("DHT_TYPE", "DHT22").strip().upper()
    DHT_POLL_INTERVAL_SEC = float(os.environ.get("DHT_POLL_INTERVAL_SEC", "2.0"))

    GPS_SERIAL = os.environ.get("GPS_SERIAL", "/dev/serial0")
    GPS_BAUD = int(os.environ.get("GPS_BAUD", "9600"))

    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "").strip()
    ALERT_PHONE_E164 = os.environ.get("ALERT_PHONE_E164", "").strip()
    SMS_COOLDOWN_SEC = int(os.environ.get("SMS_COOLDOWN_SEC", "120"))

    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    MOTION_THRESHOLD = float(os.environ.get("MOTION_THRESHOLD", "1.2"))
    MOTION_PIXEL_THRESHOLD = int(os.environ.get("MOTION_PIXEL_THRESHOLD", "22"))
    MOTION_DOWNSCALE = int(os.environ.get("MOTION_DOWNSCALE", "4"))
    INACTIVITY_SECONDS = int(os.environ.get("INACTIVITY_SECONDS", "45"))
    INACTIVITY_LED_SECONDS = float(os.environ.get("INACTIVITY_LED_SECONDS", "30"))
    INACTIVITY_BUZZER_SECONDS = float(os.environ.get("INACTIVITY_BUZZER_SECONDS", "5"))

    CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
    CAMERA_TRY_INDICES = [
        int(x.strip())
        for x in os.environ.get(
            "CAMERA_TRY_INDICES", "0,1,2,3,8,9,10,11,12,13,14,15,16,18"
        ).split(",")
        if x.strip().isdigit()
    ]
    USE_PICAMERA2 = os.environ.get("USE_PICAMERA2", "1").lower() in (
        "1",
        "true",
        "yes",
    )
    CAMERA_PREVIEW_FPS = float(os.environ.get("CAMERA_PREVIEW_FPS", "8"))
    VIDEO_STREAM_FPS = float(os.environ.get("VIDEO_STREAM_FPS", "8"))
    CAMERA_JPEG_QUALITY = int(os.environ.get("CAMERA_JPEG_QUALITY", "65"))
    CAMERA_STREAM_WIDTH = int(os.environ.get("CAMERA_STREAM_WIDTH", "480"))
    CAMERA_STREAM_HEIGHT = int(os.environ.get("CAMERA_STREAM_HEIGHT", "360"))

    SERVO_ENABLED = os.environ.get("SERVO_ENABLED", "0").lower() in (
        "1",
        "true",
        "yes",
    )
    SERVO_BASE_GPIO = int(os.environ.get("SERVO_BASE_GPIO", "25"))
    SERVO_TOP_GPIO = int(os.environ.get("SERVO_TOP_GPIO", "23"))
    SERVO_STEP_DEGREES = int(os.environ.get("SERVO_STEP_DEGREES", "15"))

    WAITRESS_THREADS = int(os.environ.get("WAITRESS_THREADS", "16"))
