"""GPIO, servos, DHT, and infrared hardware, with mock behavior when GPIO is unavailable."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

# Cache the CircuitPython DHT instance by (BCM pin, model) to avoid repeatedly creating PulseIn.
_dht_cp_dev: object | None = None
_dht_cp_key: tuple[int, str] | None = None

try:
    import RPi.GPIO as GPIO  # type: ignore

    _HAS_GPIO = True
except Exception:
    GPIO = None  # type: ignore
    _HAS_GPIO = False

if _HAS_GPIO:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)


def _servo_duty_from_angle(angle_deg: float) -> float:
    a = max(0.0, min(180.0, float(angle_deg)))
    pulse_ms = 1.0 + (a / 180.0) * 1.0
    return (pulse_ms / 20.0) * 100.0


def _dht_cp_exit(dev: object) -> None:
    try:
        ex = getattr(dev, "exit", None)
        if callable(ex):
            ex()
    except Exception:
        pass


def read_dht(gpio: int, dht_type: str) -> tuple[Optional[float], Optional[float], str]:
    """Try Blinka + adafruit_dht first, then legacy Adafruit_DHT and the system Python interpreter."""
    global _dht_cp_dev, _dht_cp_key
    typ = (dht_type or "DHT22").strip().upper()
    err = ""
    gpio = int(gpio)

    # 1) CircuitPython / Blinka, verified on Raspberry Pi without the Adafruit_DHT C library.
    try:
        import board
        import adafruit_dht

        pin_name = f"D{gpio}"
        pin = getattr(board, pin_name, None)
        if pin is None:
            raise ValueError(f"BCM{gpio} has no matching board.{pin_name}")

        key = (gpio, typ)
        if _dht_cp_dev is None or _dht_cp_key != key:
            _dht_cp_exit(_dht_cp_dev)
            _dht_cp_key = key
            if typ == "DHT11":
                _dht_cp_dev = adafruit_dht.DHT11(pin)
            elif typ in ("DHT21", "AM2301"):
                _dht_cp_dev = adafruit_dht.DHT21(pin)
            else:
                _dht_cp_dev = adafruit_dht.DHT22(pin)

        assert _dht_cp_dev is not None
        dev = _dht_cp_dev
        last_cp_err = ""
        for attempt in range(5):
            try:
                t = dev.temperature
                h = dev.humidity
                if t is not None and h is not None:
                    return float(t), float(h), ""
                if t is not None:
                    return float(t), None, "Temperature only"
                if h is not None:
                    return None, float(h), "Humidity only"
            except RuntimeError as e:
                last_cp_err = str(e)
                time.sleep(0.08 * (attempt + 1))
            except Exception as e:
                last_cp_err = str(e)
                break
        err = last_cp_err or err
    except ImportError:
        pass
    except Exception as e:
        err = str(e)

    # 2) Legacy Adafruit_DHT, preinstalled in system Python on some images.
    try:
        import Adafruit_DHT as ADHT  # type: ignore

        sensor = ADHT.DHT22 if typ in ("DHT22", "AM2302") else ADHT.DHT11
        h, t = ADHT.read_retry(sensor, gpio, retries=8, delay_seconds=0.2)
        if t is not None and h is not None:
            return float(t), float(h), ""
        if t is not None:
            return float(t), None, "Temperature only"
        if h is not None:
            return None, float(h), "Humidity only"
    except Exception as e:
        if not err:
            err = str(e)

    # 3) System python3 subprocess, when Adafruit_DHT is installed globally.
    try:
        script = (
            "import Adafruit_DHT as A\n"
            f"sensor=A.DHT22 if {repr(typ)} in ('DHT22','AM2302') else A.DHT11\n"
            f"h,t=A.read_retry(sensor, {int(gpio)})\n"
            "print(t if t is not None else '', h if h is not None else '')"
        )
        out = subprocess.run(
            ["/usr/bin/python3", "-c", script],
            capture_output=True,
            text=True,
            timeout=25,
        )
        parts = out.stdout.strip().split()
        if len(parts) >= 2:
            t_s, h_s = parts[0], parts[1]
            t = float(t_s) if t_s else None
            h = float(h_s) if h_s else None
            if t is not None and h is not None:
                return t, h, ""
    except Exception:
        pass

    return None, None, err or "DHT read failed"


class Hardware:
    def __init__(
        self,
        *,
        red_led: int,
        blue_led: int,
        red_button: int,
        ir_motion: int,
        ir_active_high: bool,
        red_button_active_high: bool = False,
        led_active_low: bool,
        buzzer_gpio: Optional[int] = None,
        buzzer_active_low: bool = True,
        servo_base_gpio: Optional[int] = None,
        servo_top_gpio: Optional[int] = None,
    ) -> None:
        self.red_led = red_led
        self.blue_led = blue_led
        self.red_button = red_button
        self.ir_motion = ir_motion
        self._ir_active_high = ir_active_high
        self._red_button_active_high = red_button_active_high
        self._led_active_low = led_active_low
        self.buzzer_gpio = int(buzzer_gpio) if buzzer_gpio else None
        self._buzzer_active_low = buzzer_active_low
        self.servo_base_gpio = servo_base_gpio
        self.servo_top_gpio = servo_top_gpio
        self._servo_base_pwm = None
        self._servo_top_pwm = None
        self._lock = threading.Lock()
        self._mock = not _HAS_GPIO

        if self._mock:
            log.warning("RPi.GPIO is unavailable; using mock hardware")
            return

        GPIO.setup(self.red_led, GPIO.OUT)
        GPIO.setup(self.blue_led, GPIO.OUT)
        GPIO.setup(self.ir_motion, GPIO.IN)
        if self.buzzer_gpio is not None:
            GPIO.setup(self.buzzer_gpio, GPIO.OUT)
        if self.servo_base_gpio is not None:
            GPIO.setup(self.servo_base_gpio, GPIO.OUT)
            self._servo_base_pwm = GPIO.PWM(self.servo_base_gpio, 50)
            self._servo_base_pwm.start(_servo_duty_from_angle(90))
        if self.servo_top_gpio is not None:
            GPIO.setup(self.servo_top_gpio, GPIO.OUT)
            self._servo_top_pwm = GPIO.PWM(self.servo_top_gpio, 50)
            self._servo_top_pwm.start(_servo_duty_from_angle(90))

        self.set_red_led(False)
        self.set_blue_led(False)
        self.set_buzzer(False)
        if self._red_button_active_high:
            GPIO.setup(self.red_button, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        else:
            GPIO.setup(self.red_button, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def _led_pin_level(self, on: bool) -> bool:
        if self._led_active_low:
            return not on
        return on

    def set_red_led(self, on: bool) -> None:
        if self._mock:
            log.debug("MOCK red_led=%s", on)
            return
        with self._lock:
            GPIO.output(self.red_led, self._led_pin_level(on))

    def set_blue_led(self, on: bool) -> None:
        if self._mock:
            log.debug("MOCK blue_led=%s", on)
            return
        with self._lock:
            GPIO.output(self.blue_led, self._led_pin_level(on))

    def set_buzzer(self, on: bool) -> None:
        if self.buzzer_gpio is None:
            return
        if self._mock:
            log.debug("MOCK buzzer=%s", on)
            return
        quiet = self._buzzer_active_low
        loud = not quiet
        with self._lock:
            GPIO.output(self.buzzer_gpio, loud if on else quiet)

    def read_red_button(self) -> bool:
        if self._mock:
            return False
        v = GPIO.input(self.red_button)
        if self._red_button_active_high:
            return v == GPIO.HIGH
        return v == GPIO.LOW

    def read_ir_motion(self) -> bool:
        if self._mock:
            return True
        v = GPIO.input(self.ir_motion)
        if os.environ.get("IR_INVERT", "").lower() in ("1", "true"):
            v = GPIO.HIGH if v == GPIO.LOW else GPIO.LOW
        if self._ir_active_high:
            return v == GPIO.HIGH
        return v == GPIO.LOW

    def set_servo_angle(self, axis: str, angle_deg: float) -> None:
        axis = axis.strip().lower()
        pwm = self._servo_base_pwm if axis == "base" else self._servo_top_pwm
        if pwm is None:
            return
        duty = _servo_duty_from_angle(angle_deg)
        with self._lock:
            try:
                pwm.ChangeDutyCycle(duty)
            except Exception:
                log.exception("Servo PWM error")
