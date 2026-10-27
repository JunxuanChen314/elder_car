# Elder Car

Elder Car is a Raspberry Pi–based safety and remote-monitoring platform designed for an assistive care vehicle. It combines live video, environmental sensing, GPS, infrared presence detection, camera-based motion analysis, physical emergency controls, indicator LEDs, a buzzer, and remote Telegram or Twilio alerts in one browser dashboard.

The system is built as a local edge application: the Raspberry Pi reads the sensors, analyzes camera frames, controls the attached hardware, serves an MJPEG video stream, and exposes a Flask dashboard over the network. It can continue monitoring locally even when external notification services are unavailable.

## Key Features

- Live camera feed through Picamera2 with automatic OpenCV fallback
- Camera-frame motion analysis for prolonged-inactivity detection
- Infrared presence sensing to reduce false inactivity alerts when nobody is present
- DHT11/DHT22 ambient temperature and humidity monitoring
- Raspberry Pi SoC temperature monitoring
- UART GPS parsing with live coordinates, satellite count, and embedded maps
- Physical red emergency button with toggle-to-clear behavior
- Red emergency LED, blue inactivity LED, and optional buzzer feedback
- Browser controls for a two-axis pan-tilt servo mount
- Telegram Bot and Twilio SMS alert delivery with shared cooldown protection
- Optional HTTP Basic Authentication for the dashboard and API
- Waitress production server and an included systemd service template
- Mock-hardware fallback so the web application can run without Raspberry Pi GPIO

## System Architecture

```text
Camera / Picamera2 -------+
DHT11 or DHT22 -----------+
UART GPS -----------------+
Infrared sensor ----------+--> Raspberry Pi --> Flask + Waitress --> Browser dashboard
Emergency button ---------+         |                  |              |  live MJPEG video
Pan-tilt servos -----------+         |                  |              |  maps and telemetry
LEDs + optional buzzer ----+         |                  |              |  servo controls
                                    |                  |
                                    +--> OpenCV motion analysis
                                    +--> Telegram Bot API
                                    +--> Twilio SMS API
```

- Background Python threads independently update the camera, DHT, GPS, and GPIO state.
- A thread-safe in-memory state object provides fast dashboard snapshots and an 80-entry event buffer.
- OpenCV downsamples grayscale frames and measures the fraction of pixels whose change exceeds the configured threshold.
- Inactivity alerts require recent infrared presence and prolonged low camera motion.
- The Flask API exposes status, video, servo, and LED endpoints to the browser.

## Hardware

The current configuration is designed for a Raspberry Pi and the following components:

- Raspberry Pi with a CSI or USB camera
- DHT11 or DHT22 temperature and humidity sensor
- UART GPS module that outputs NMEA RMC/GGA sentences
- Infrared motion or presence sensor
- Momentary red emergency button
- Red status LED
- Blue status LED
- Optional active-low buzzer module
- Two PWM servos for camera pan and tilt
- Shared power and ground appropriate for the selected modules

## Default GPIO and Device Mapping

| Function | Default connection | Configuration |
|---|---:|---|
| Red emergency LED | BCM GPIO 24 | `RED_LED_GPIO` |
| Blue inactivity LED | BCM GPIO 17 | `BLUE_LED_GPIO` |
| Red emergency button | BCM GPIO 27 | `RED_BUTTON_GPIO` |
| Infrared sensor | BCM GPIO 4 | `IR_MOTION_GPIO` |
| DHT sensor data | BCM GPIO 18 | `DHT_GPIO` |
| Pan/base servo | BCM GPIO 25 | `SERVO_BASE_GPIO` |
| Tilt/top servo | BCM GPIO 23 | `SERVO_TOP_GPIO` |
| Buzzer | Disabled until configured | `BUZZER_GPIO` |
| GPS serial device | `/dev/serial0` | `GPS_SERIAL` |
| GPS baud rate | `9600` | `GPS_BAUD` |

GPIO numbering uses the Raspberry Pi BCM scheme. Confirm the voltage, current, grounding, and level-shifting requirements of the exact hardware before connecting it. Servos should use an adequate external power supply when necessary; do not draw unsafe current from a Raspberry Pi GPIO pin.

## Monitoring and Alert Logic

### Emergency button

Pressing the red button activates the emergency state, turns on the red LED, starts the buzzer when configured, and dispatches a remote alert. Pressing the button again clears the emergency state, turns the outputs off, and sends an alert-cleared notification.

The default input assumes a button connected to ground with the Raspberry Pi internal pull-up. Set `RED_BUTTON_ACTIVE_HIGH=1` for a circuit that reads HIGH when pressed and uses an internal pull-down.

### Prolonged inactivity

The application converts each camera frame to grayscale, downsamples it, compares it with the preceding frame, and reports the changed-pixel percentage as a motion score. An inactivity alert is generated only when:

1. the infrared sensor has detected presence recently;
2. the motion score remains below `MOTION_THRESHOLD`; and
3. the condition lasts for at least `INACTIVITY_SECONDS`.

When triggered, the blue LED activates, the optional buzzer sounds briefly, and the application attempts a remote notification. Motion clears the alert. If infrared presence expires, the application also clears the alert instead of treating an empty scene as an emergency.

Default timing and detection values:

| Parameter | Default | Purpose |
|---|---:|---|
| `MOTION_THRESHOLD` | `1.2` | Minimum changed-pixel percentage treated as motion |
| `MOTION_PIXEL_THRESHOLD` | `22` | Per-pixel grayscale difference threshold |
| `MOTION_DOWNSCALE` | `4` | Frame reduction factor used during analysis |
| `INACTIVITY_SECONDS` | `45` | Low-motion duration before an alert |
| `IR_PRESENCE_HOLD_SECONDS` | `180` | How long a recent IR detection counts as presence |
| `INACTIVITY_LED_SECONDS` | `30` | Blue LED alert duration |
| `INACTIVITY_BUZZER_SECONDS` | `5` | Buzzer pulse duration |
| `SMS_COOLDOWN_SEC` | `120` | Minimum interval between alerts with the same key |

These values are prototype defaults and should be tuned for the room, camera position, lighting, and intended care workflow. Elder Car is not a certified medical device or a replacement for professional emergency monitoring.

## Dashboard

The responsive browser dashboard displays:

- live MJPEG camera video;
- pan and tilt controls from 0° to 180°;
- ambient temperature and humidity;
- Raspberry Pi board temperature;
- blue and red alert status;
- live motion score and infrared input state;
- GPS position, satellite status, Google Maps, and OpenStreetMap links; and
- recent timestamped system events.

The browser uses a fast heartbeat endpoint for alerts and event updates and a full status endpoint for camera, environmental, GPS, and servo state. If the heartbeat endpoint is unavailable, the frontend falls back to status polling.

## Technology Stack

- Runtime: Python 3
- Web application: Flask 3
- Production server: Waitress
- Computer vision: OpenCV, NumPy
- Raspberry Pi camera: Picamera2 with OpenCV fallback
- GPIO: RPi.GPIO
- Environmental sensing: Adafruit CircuitPython DHT, Adafruit Blinka
- GPS: pySerial and NMEA parsing
- Notifications: Telegram Bot HTTP API, Twilio Python SDK
- Frontend: HTML, CSS, JavaScript
- Maps: Google Maps embed and OpenStreetMap links
- Deployment: Linux, systemd, `.env` configuration

## Repository Structure

```text
elder_car/
├── app/
│   ├── __init__.py          Flask application and API routes
│   ├── hardware.py          GPIO, LEDs, buzzer, servos, IR, and DHT access
│   ├── notifier.py          Telegram and Twilio delivery with cooldowns
│   ├── pi_paths.py          Raspberry Pi system-package path support
│   └── services.py          State, background workers, camera, GPS, and alert logic
├── extras/
│   ├── gps-serial-setup.txt GPS serial troubleshooting
│   └── udev/                Serial-device permission rule
├── static/
│   ├── css/style.css        Dashboard styling
│   └── js/app.js            Live polling, maps, and servo UI
├── templates/index.html     Dashboard markup
├── config.py                Environment-driven configuration
├── elder-car.service.example
├── requirements.txt
└── run.py                   Development or Waitress entry point
```

## Prerequisites

- Raspberry Pi OS or another Linux environment with Python 3
- A Raspberry Pi for GPIO, Picamera2, and SoC temperature support
- Camera and sensors required by the selected features
- Network access only if Telegram, Twilio, or external map tiles are used

The application can start on a non-Raspberry Pi computer. GPIO-dependent features use mock behavior, and camera or sensor status will report unavailable hardware.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/JunxuanChen314/elder_car.git
cd elder_car
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Picamera2 and RPi.GPIO are normally installed through Raspberry Pi OS packages rather than pip. The application includes `app/pi_paths.py` so a virtual environment can load supported system-installed packages.

### 3. Configure the environment

Create a local `.env` file in the repository root. It is ignored by Git.

```dotenv
SECRET_KEY=replace_with_a_random_value

# Optional dashboard authentication
WEB_BASIC_AUTH_USER=admin
WEB_BASIC_AUTH_PASSWORD=replace_with_a_strong_password

# GPIO
RED_LED_GPIO=24
BLUE_LED_GPIO=17
RED_BUTTON_GPIO=27
IR_MOTION_GPIO=4
DHT_GPIO=18
DHT_TYPE=DHT22

# Optional buzzer and pan-tilt servos
BUZZER_GPIO=22
SERVO_ENABLED=1
SERVO_BASE_GPIO=25
SERVO_TOP_GPIO=23

# GPS
GPS_SERIAL=/dev/serial0
GPS_BAUD=9600

# Optional Telegram alerts
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Optional Twilio SMS alerts
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=your_twilio_number
ALERT_PHONE_E164=your_recipient_number
```

Never commit `.env`, access tokens, API credentials, or phone numbers.

### 4. Start the application

Production-style local server:

```bash
source .venv/bin/activate
python run.py
```

Development server:

```bash
USE_FLASK_DEV=1 python run.py
```

The server listens on `0.0.0.0:5000`. Open `http://<raspberry-pi-address>:5000/` from a device on the same network.

## systemd Deployment

The included service file assumes the repository is located at `/home/junxuanchen/elder_car` and the virtual environment is `.venv`.

```bash
sudo cp elder-car.service.example /etc/systemd/system/elder-car.service
sudo systemctl daemon-reload
sudo systemctl enable --now elder-car
sudo systemctl status elder-car
```

To view logs:

```bash
journalctl -u elder-car -f
```

Edit the `User`, `Group`, `WorkingDirectory`, `Environment`, and `ExecStart` entries if your installation path or account differs.

## GPS Serial Setup

The service account must be able to read the configured serial device. The provided systemd template includes:

```ini
SupplementaryGroups=dialout gpio video
```

If `/dev/ttyS0` remains owned by `root:root` with mode `0600`, install the provided udev rule:

```bash
sudo cp extras/udev/99-elder-gps-serial.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

If `serial-getty@ttyS0` is claiming the mini UART, disable it:

```bash
sudo systemctl mask --now serial-getty@ttyS0.service
```

See `extras/gps-serial-setup.txt` for restoration steps and USB serial alternatives.

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Dashboard |
| `GET` | `/video_feed` | MJPEG camera stream |
| `GET` | `/api/heartbeat` | Fast alert, event, motion, environment, and GPS snapshot |
| `GET` | `/api/status` | Full application and hardware state |
| `GET` | `/api/state` | Backward-compatible alias for `/api/status` |
| `POST` | `/api/hardware/servo` | Set a servo by absolute `angle` or relative `delta` |
| `POST` | `/api/hardware/led` | Set the `red` or `blue` LED state |

Example servo request:

```bash
curl -X POST http://127.0.0.1:5000/api/hardware/servo \
  -H 'Content-Type: application/json' \
  -d '{"axis":"base","angle":90}'
```

Example LED request:

```bash
curl -X POST http://127.0.0.1:5000/api/hardware/led \
  -H 'Content-Type: application/json' \
  -d '{"color":"blue","on":true}'
```

When Basic Authentication is enabled, all dashboard and API requests require the configured credentials.

## Notification Behavior

Telegram and Twilio are optional and can be enabled independently or together. Alerts run asynchronously so external network latency does not block sensor processing. Notification keys share a cooldown table, which prevents the same event type from sending continuously.

The project does not include any credentials. Configuration values are loaded from environment variables, and `.env` is excluded by `.gitignore`.

## Validation

Basic syntax validation:

```bash
python -m compileall app config.py run.py
```

Start the application on development hardware and verify:

1. the dashboard loads and reports the expected camera and sensor status;
2. the red button toggles the emergency state;
3. the LEDs and optional buzzer follow the dashboard state;
4. the DHT readings and Raspberry Pi board temperature update;
5. GPS progresses from satellite search to a valid location;
6. servo controls move only within the safe mechanical range; and
7. configured Telegram or Twilio alerts arrive once per cooldown interval.

## Safety and Limitations

- Elder Car is a prototype and is not a certified medical, life-safety, or emergency-response device.
- Camera-based motion is sensitive to lighting, camera vibration, occlusion, and scene layout.
- GPS accuracy depends on the module, antenna, sky visibility, and environment.
- Secure the dashboard with Basic Authentication and an appropriate private network or VPN before exposing it beyond a trusted LAN.
- Verify servo travel limits and power requirements before enabling movement.
- Test every alert channel regularly; local indicators do not guarantee remote message delivery.

## License

No license has been added. All rights are reserved unless the repository owner states otherwise.
