"""Custom text with time, date and city variables."""
from datetime import datetime


def get_text(options):
    now = datetime.now()
    variables = {"time": now.strftime("%H:%M"), "date": now.strftime("%d/%m/%Y"), "city": str(options.get("city", "Paris"))}
    try:
        return str(options.get("message", "")).format_map(variables)
    except (KeyError, ValueError):
        return str(options.get("message", ""))
