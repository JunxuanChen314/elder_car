"""Allow the virtual environment to load apt-installed packages such as picamera2 and Adafruit_DHT."""
import os
import sys


def prepend_system_dist_packages() -> None:
    v = f"{sys.version_info.major}.{sys.version_info.minor}"
    for p in (f"/usr/lib/python{v}/dist-packages", "/usr/lib/python3/dist-packages"):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
