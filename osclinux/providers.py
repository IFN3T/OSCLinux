"""Data providers for the built-in chatbox modules."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from concurrent.futures import Future


class WeatherProvider:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="osclinux-weather")
        self._lock = threading.Lock()
        self._next_refresh = 0.0
        self._text = "Météo indisponible"

    def get(self, city: str, unit: str) -> str:
        now = time.monotonic()
        if now >= self._next_refresh:
            self._next_refresh = now + 900
            self._executor.submit(self._fetch, city, unit)
        with self._lock:
            return self._text

    def _fetch(self, city: str, unit: str) -> None:
        try:
            name = urllib.parse.urlencode({"name": city, "count": 1, "language": "fr", "format": "json"})
            location = _get_json(f"https://geocoding-api.open-meteo.com/v1/search?{name}")
            results = location.get("results") or []
            if not results:
                raise ValueError("Ville introuvable")
            place = results[0]
            query = urllib.parse.urlencode({
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,weather_code",
                "temperature_unit": "fahrenheit" if unit == "°F" else "celsius",
            })
            current = _get_json(f"https://api.open-meteo.com/v1/forecast?{query}")["current"]
            text = f"{place['name']} · {_weather_label(int(current['weather_code']))} · {round(float(current['temperature_2m']))}{unit}"
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            text = f"Météo indisponible ({exc})"
        with self._lock:
            self._text = text

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "OSCLinux/0.1", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read(1_000_000).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Réponse météo invalide")
    return payload


def _weather_label(code: int) -> str:
    if code == 0:
        return "Ensoleillé"
    if code in (1, 2, 3):
        return "Nuageux"
    if code in (45, 48):
        return "Brouillard"
    if code in (51, 53, 55, 56, 57):
        return "Bruine"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "Pluie"
    if code in (71, 73, 75, 77, 85, 86):
        return "Neige"
    if code in (95, 96, 99):
        return "Orage"
    return "Temps variable"


def spotify_text(hide_paused: bool = True, track_format: str = "Titre + Artiste + Progression") -> str:
    playerctl = shutil.which("playerctl")
    if not playerctl:
        return "Spotify · playerctl absent"
    try:
        result = subprocess.run(
            [playerctl, "metadata", "--format", "{{title}}\t{{artist}}\t{{status}}\t{{position}}\t{{mpris:length}}"],
            capture_output=True,
            text=True,
            timeout=0.7,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return "Spotify · aucun lecteur actif"
        title, artist, status, position, duration = (result.stdout.strip().split("\t") + [""] * 5)[:5]
        if hide_paused and status.lower() != "playing":
            return ""
        title = title or "Lecture en cours"
        artist = artist or "Artiste inconnu"
        if position and duration:
            elapsed, total = int(float(position)), int(float(duration) / 1_000_000)
            progress = f"{elapsed // 60:02d}:{elapsed % 60:02d} / {total // 60:02d}:{total % 60:02d}"
            if track_format == "Titre + Artiste":
                return f"♫ {title} — {artist}"
            if track_format == "Artiste + Titre":
                return f"♫ {artist} — {title}"
            return f"♫ {title} — {artist} · {progress}"
        if track_format == "Artiste + Titre":
            return f"♫ {artist} — {title}"
        return f"♫ {title} — {artist}"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "Spotify · lecture impossible"


def system_text(options: dict) -> str:
    cpu = _cpu_percent()
    ram = _ram_percent()
    values = []
    if options.get("cpu", True):
        values.append(f"CPU {cpu}%")
    if options.get("ram", True):
        values.append(f"RAM {ram}%")
    if options.get("gpu", True):
        gpu = _gpu_percent()
        if gpu is not None:
            values.append(f"GPU {gpu}%")
    return "  |  ".join(values) or "Ressources système"


def temperature_text(options: dict) -> str:
    values = []
    if options.get("cpu", True):
        cpu_temps = _thermal_temps()
        if cpu_temps:
            values.append(f"CPU {max(cpu_temps):.0f}°C")
    if options.get("gpu", True):
        result = _nvidia_smi("--query-gpu=temperature.gpu", "--format=csv,noheader,nounits")
        if result:
            values.append(f"GPU {result.splitlines()[0].strip()}°C")
    return "  |  ".join(values) or "Capteurs thermiques indisponibles"


def _cpu_percent() -> int:
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


def _ram_percent() -> int:
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0])
        return round(100 * (values["MemTotal"] - values.get("MemAvailable", values.get("MemFree", 0))) / values["MemTotal"])
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        return 0


def _nvidia_smi(*arguments: str) -> str | None:
    command = shutil.which("nvidia-smi")
    if not command:
        return None
    try:
        result = subprocess.run([command, *arguments], capture_output=True, text=True, timeout=1, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _gpu_percent() -> int | None:
    output = _nvidia_smi("--query-gpu=utilization.gpu", "--format=csv,noheader,nounits")
    try:
        return round(float(output.splitlines()[0])) if output else None
    except (ValueError, IndexError):
        return None


def _thermal_temps() -> list[float]:
    values = []
    for sensor in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = float(sensor.read_text().strip())
            values.append(value / 1000 if value > 1000 else value)
        except (OSError, ValueError):
            continue
    return values


def module_text(key: str, options: dict, weather: WeatherProvider) -> str:
    if key == "spotify":
        return spotify_text(bool(options.get("hide_paused", True)), str(options.get("format", "Titre + Artiste + Progression")))
    if key == "system":
        return system_text(options)
    if key == "temperatures":
        return temperature_text(options)
    if key == "weather":
        return weather.get(str(options.get("city", "Paris")), str(options.get("unit", "°C")))
    if key == "clock":
        return datetime.now().strftime("%I:%M %p" if options.get("format") == "12h" else "%H:%M")
    if key == "custom":
        now = datetime.now()
        variables = {"time": now.strftime("%H:%M"), "date": now.strftime("%d/%m/%Y"), "city": str(options.get("city", "Paris"))}
        try:
            return str(options.get("message", "")).format_map(variables)
        except (KeyError, ValueError):
            return str(options.get("message", ""))
    return ""


class ModuleDataProvider:
    """Refresh module data off the Qt thread and serve the latest cached value."""

    def __init__(self, weather: WeatherProvider) -> None:
        self.weather = weather
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="osclinux-module")
        self._lock = threading.Lock()
        self._values: dict[tuple[str, str], str] = {}
        self._next_refresh: dict[tuple[str, str], float] = {}
        self._pending: set[tuple[str, str]] = set()

    def get(self, key: str, options: dict) -> str:
        signature = json.dumps(options, ensure_ascii=False, sort_keys=True, default=str)
        cache_key = (key, signature)
        with self._lock:
            value = self._values.get(cache_key, "Chargement…")
            due = time.monotonic() >= self._next_refresh.get(cache_key, 0)
            if due and cache_key not in self._pending:
                self._next_refresh[cache_key] = time.monotonic() + 2
                self._pending.add(cache_key)
                future = self._executor.submit(module_text, key, options, self.weather)
                future.add_done_callback(lambda result, cache_key=cache_key: self._complete(cache_key, result))
            return value

    def _complete(self, key: tuple[str, str], future: Future) -> None:
        try:
            value = str(future.result())
        except Exception as exc:
            value = f"Indisponible : {exc}"
        with self._lock:
            self._values[key] = value
            self._pending.discard(key)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
