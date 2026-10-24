"""Read a selected MPRIS media player's status through playerctl."""
import shutil
import subprocess


def get_text(options):
    playerctl = shutil.which("playerctl")
    if not playerctl:
        return "Lecteur Audio · playerctl absent"
    player = str(options.get("player", "spotify")).strip() or "spotify"
    try:
        result = subprocess.run(
            [playerctl, f"--player={player}", "metadata", "--format", "{{title}}\t{{artist}}\t{{status}}\t{{position}}\t{{mpris:length}}"],
            capture_output=True, text=True, timeout=0.7, check=False,
        )
        if result.returncode or not result.stdout.strip():
            return f"Lecteur Audio · aucun média actif ({player})"
        title, artist, status, position, duration = (result.stdout.strip().split("\t") + [""] * 5)[:5]
        if options.get("hide_paused", True) and status.lower() != "playing":
            return ""
        title, artist = title or "Lecture en cours", artist or "Artiste inconnu"
        track_format = options.get("format", "Titre + Artiste + Progression")
        if track_format == "Artiste + Titre":
            return f"♫ {artist} — {title}"
        if track_format == "Titre + Artiste":
            return f"♫ {title} — {artist}"
        if position and duration:
            elapsed, total = int(float(position)), int(float(duration) / 1_000_000)
            return f"♫ {title} — {artist} · {elapsed // 60:02d}:{elapsed % 60:02d} / {total // 60:02d}:{total % 60:02d}"
        return f"♫ {title} — {artist}"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return f"Lecteur Audio · lecture impossible ({player})"
