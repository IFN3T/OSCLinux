"""Local time in 12-hour or 24-hour format."""
from datetime import datetime


def get_text(options):
    return datetime.now().strftime("%I:%M %p" if options.get("format") == "12h" else "%H:%M")
