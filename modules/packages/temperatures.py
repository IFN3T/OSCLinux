"""Report CPU, RAM, NVIDIA GPU, and other Linux hardware temperatures."""
import shutil
import subprocess
from pathlib import Path


HWMON_ROOT = Path("/sys/class/hwmon")
CPU_CHIPS = {"coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu"}
RAM_CHIPS = {"jc42", "spd5118", "spd1200", "spd"}


def get_text(options):
    values = []
    readings = _hwmon_readings()
    if options.get("cpu", True):
        cpu_temps = [temp for chip, _label, temp in readings if _is_cpu_chip(chip)]
        if cpu_temps:
            values.append(f"CPU {max(cpu_temps):.0f}°C")
        else:
            thermal_temps = _thermal_temps()
            if thermal_temps:
                values.append(f"CPU {max(thermal_temps):.0f}°C")
    if options.get("ram", True):
        ram_temps = [temp for chip, _label, temp in readings if _is_ram_chip(chip)]
        values.extend(f"RAM{index} {temp:.0f}°C" for index, temp in enumerate(ram_temps))
    if options.get("gpu", True):
        values.extend(f"GPU{index} {temperature}°C" for index, temperature in _nvidia_temperatures())
    if options.get("other", False):
        values.extend(_other_sensor_text(readings))
    return "  |  ".join(values) or "Capteurs thermiques indisponibles"


def _hwmon_readings():
    readings = []
    for device in sorted(HWMON_ROOT.glob("hwmon*")):
        try:
            chip = (device / "name").read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        for sensor in sorted(device.glob("temp*_input")):
            try:
                raw_temp = float(sensor.read_text(encoding="utf-8").strip())
                temperature = raw_temp / 1000 if abs(raw_temp) >= 1000 else raw_temp
                if not -40 <= temperature <= 150:
                    continue
                label_path = sensor.with_name(sensor.name.removesuffix("_input") + "_label")
                label = label_path.read_text(encoding="utf-8").strip() if label_path.is_file() else sensor.stem
                readings.append((chip, label, temperature))
            except (OSError, ValueError):
                continue
    return readings


def _is_cpu_chip(chip):
    return chip in CPU_CHIPS or "cpu" in chip or "coretemp" in chip or "k10temp" in chip


def _is_ram_chip(chip):
    return chip in RAM_CHIPS or chip.startswith("jc") or chip.startswith("spd")


def _thermal_temps():
    values = []
    for sensor in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = float(sensor.read_text(encoding="utf-8").strip())
            values.append(value / 1000 if abs(value) >= 1000 else value)
        except (OSError, ValueError):
            continue
    return [value for value in values if -40 <= value <= 150]


def _nvidia_temperatures():
    command = shutil.which("nvidia-smi")
    if not command:
        return []
    try:
        result = subprocess.run(
            [command, "--query-gpu=index,temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=1, check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        readings = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",", 1)]
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                readings.append((int(parts[0]), int(parts[1])))
        return sorted(readings)
    except (OSError, subprocess.TimeoutExpired):
        return []


def _other_sensor_text(readings):
    values = []
    for chip, label, temperature in readings:
        if _is_cpu_chip(chip) or _is_ram_chip(chip):
            continue
        if chip.startswith("nvidia") or chip.startswith("amdgpu"):
            continue
        name = label if label and not label.startswith("temp") else chip
        values.append(f"{name} {temperature:.0f}°C")
    return values
