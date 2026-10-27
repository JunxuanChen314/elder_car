import logging
import os

from flask import Flask, Response, jsonify, render_template, request

from config import Config

log = logging.getLogger("app")


def create_app() -> Flask:
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(pkg_dir)
    app = Flask(
        __name__,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )
    app.secret_key = getattr(Config, "SECRET_KEY", "dev")

    from .services import mjpeg_generator, set_led_manual, set_servo_from_web, start_background

    start_background(app)

    @app.before_request
    def _optional_basic_auth():
        u = getattr(Config, "WEB_BASIC_AUTH_USER", "") or ""
        p = getattr(Config, "WEB_BASIC_AUTH_PASSWORD", "") or ""
        if not u or not p:
            return None
        auth = request.authorization
        if auth and auth.username == u and auth.password == p:
            return None
        return Response(
            "Username and password required",
            401,
            {
                "WWW-Authenticate": 'Basic realm="Elder Car"',
                "Content-Type": "text/plain; charset=utf-8",
            },
        )

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/heartbeat")
    def api_heartbeat():
        from .services import STATE

        try:
            return jsonify(STATE.heartbeat_snapshot())
        except Exception:
            log.exception("api_heartbeat failed")
            return jsonify(
                {
                    "red_led": False,
                    "emergency_active": False,
                    "blue_led": False,
                    "inactivity_alert": False,
                    "events": [],
                    "temperature_c": None,
                    "humidity_pct": None,
                    "board_temp_c": None,
                    "dht_ok": False,
                    "temperature_source": "none",
                    "dht_error": "",
                    "gps_lat": None,
                    "gps_lon": None,
                    "gps_status": "",
                    "gps_sats": 0,
                    "motion_score": 0.0,
                    "ir_motion": False,
                }
            )

    def _api_status_json():
        from .services import STATE

        try:
            return jsonify(STATE.snapshot())
        except Exception:
            log.exception("api_status snapshot failed")
            return jsonify(
                {
                    "temperature_c": None,
                    "humidity_pct": None,
                    "board_temp_c": None,
                    "dht_ok": False,
                    "motion_score": 0.0,
                    "last_ir_motion_ts": 0.0,
                    "inactivity_alert": False,
                    "emergency_active": False,
                    "ir_motion": False,
                    "red_led": False,
                    "blue_led": False,
                    "blue_led_until_ts": 0.0,
                    "inactivity_buzzer_until_ts": 0.0,
                    "camera_ok": False,
                    "camera_error": "Snapshot error",
                    "gps_lat": None,
                    "gps_lon": None,
                    "gps_status": "",
                    "gps_sats": 0,
                    "temperature_source": "none",
                    "dht_error": "",
                    "servo_base_deg": 90,
                    "servo_top_deg": 90,
                    "servo_enabled": False,
                    "servo_ui_only": False,
                    "servo_step_deg": 15,
                    "events": [],
                }
            )

    @app.route("/api/status")
    def api_status():
        return _api_status_json()

    @app.route("/api/state")
    def api_state():
        """Alias for /api/status, retained for older frontends and cached scripts."""
        return _api_status_json()

    @app.route("/video_feed")
    def video_feed():
        boundary = b"frame"
        return Response(
            mjpeg_generator(boundary),
            mimetype="multipart/x-mixed-replace; boundary=" + boundary.decode(),
        )

    @app.route("/api/hardware/servo", methods=["POST"])
    def api_servo():
        data = request.get_json(silent=True) or {}
        axis = str(data.get("axis", ""))
        angle = data.get("angle")
        delta = data.get("delta")
        if angle is not None:
            try:
                angle = float(angle)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "Invalid angle"}), 400
        if delta is not None:
            try:
                delta = float(delta)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "Invalid delta"}), 400
        ok, err = set_servo_from_web(axis, angle, delta)
        if ok:
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": err}), 400

    @app.route("/api/hardware/led", methods=["POST"])
    def api_led():
        data = request.get_json(silent=True) or {}
        color = str(data.get("color", ""))
        on = bool(data.get("on"))
        ok, err = set_led_manual(color, on)
        if ok:
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": err}), 400

    return app
