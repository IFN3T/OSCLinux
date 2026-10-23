"""Thermal zone and optional NVIDIA GPU temperature readings."""
import shutil
import subprocess
from pathlib import Path


def get_text(options):
    values = []
    if options.get("cpu", True):
        temps = _thermal_temps()
        if temps:
            values.append(f"CPU {max(temps):.0f}°C")
    if options.get("gpu", True):
        gpu = _nvidia_temperature()
        if gpu:
            values.append(f"GPU {gpu}°C")
    if options.get("other", False):
        temps = _thermal_temps()
        if len(temps) > 1:
            values.append(f"Autre {min(temps):.0f}°C")
    return "  |  ".join(values) or "Capteurs thermiques indisponibles"


def _thermal_temps():
    values = []
    for sensor in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = float(sensor.read_text().strip())
            values.append(value / 1000 if value > 1000 else value)
        except (OSError, ValueError):
            continue
    return values


def _nvidia_temperature():
    command = shutil.which("nvidia-smi")
    if not command:
        return None
    try:
        result = subprocess.run([command, "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=1, check=False)
        return result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else None
    except (OSError, IndexError, subprocess.TimeoutExpired):
        return None
