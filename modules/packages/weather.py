"""Current weather for a configured city using the Open-Meteo public API."""
import json
import urllib.parse
import urllib.request


def get_text(options):
    city = str(options.get("city", "Paris"))
    unit = str(options.get("unit", "°C"))
    try:
        query = urllib.parse.urlencode({"name": city, "count": 1, "language": "fr", "format": "json"})
        location = _get_json(f"https://geocoding-api.open-meteo.com/v1/search?{query}")
        results = location.get("results") or []
        if not results:
            return f"Météo · ville introuvable ({city})"
        place = results[0]
        query = urllib.parse.urlencode({
            "latitude": place["latitude"], "longitude": place["longitude"],
            "current": "temperature_2m,weather_code",
            "temperature_unit": "fahrenheit" if unit == "°F" else "celsius",
        })
        current = _get_json(f"https://api.open-meteo.com/v1/forecast?{query}")["current"]
        return f"{place['name']} · {_weather_label(int(current['weather_code']))} · {round(float(current['temperature_2m']))}{unit}"
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        return f"Météo indisponible ({exc})"


def _get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "OSCLinux-Weather/1", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read(1_000_000).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Réponse météo invalide")
    return payload


def _weather_label(code):
    if code == 0: return "Ensoleillé"
    if code in (1, 2, 3): return "Nuageux"
    if code in (45, 48): return "Brouillard"
    if code in (51, 53, 55, 56, 57): return "Bruine"
    if code in (61, 63, 65, 66, 67, 80, 81, 82): return "Pluie"
    if code in (71, 73, 75, 77, 85, 86): return "Neige"
    if code in (95, 96, 99): return "Orage"
    return "Temps variable"
