#!/usr/bin/env python3
"""Elder Car dashboard entry point. Uses multithreaded Waitress by default; set USE_FLASK_DEV=1 for development."""
import os

from app.pi_paths import prepend_system_dist_packages

prepend_system_dist_packages()

from app import create_app
from config import Config

app = create_app()

if __name__ == "__main__":
    if os.environ.get("USE_FLASK_DEV", "").lower() in ("1", "true", "yes"):
        app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
    else:
        from waitress import serve

        threads = max(1, int(getattr(Config, "WAITRESS_THREADS", 16) or 16))
        serve(app, host="0.0.0.0", port=5000, threads=threads)
