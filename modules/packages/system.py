"""CPU, RAM and optional NVIDIA GPU usage."""
import shutil
import subprocess
from pathlib import Path


def get_text(options):
    values = []
    if options.get("cpu", True):
        values.append(f"CPU {_cpu_percent()}%")
    if options.get("ram", True):
        values.append(f"RAM {_ram_percent()}%")
    if options.get("gpu", True):
        gpu = _gpu_percent()
        if gpu is not None:
            values.append(f"GPU {gpu}%")
    return "  |  ".join(values) or "Ressources système"


def _cpu_percent():
    try:
        values = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        previous = getattr(_cpu_percent, "previous", (total, idle))
        _cpu_percent.previous = (total, idle)
        dt, di = total - previous[0], idle - previous[1]
        return round(100 * (dt - di) / dt) if dt > 0 else 0
    except (OSError, ValueError, IndexError):
        return 0


def _ram_percent():
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0])
        return round(100 * (values["MemTotal"] - values.get("MemAvailable", values.get("MemFree", 0))) / values["MemTotal"])
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        return 0


def _gpu_percent():
    command = shutil.which("nvidia-smi")
    if not command:
        return None
    try:
        result = subprocess.run([command, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=1, check=False)
        return round(float(result.stdout.strip().splitlines()[0])) if result.returncode == 0 else None
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None
