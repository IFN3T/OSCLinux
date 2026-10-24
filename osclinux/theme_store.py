"""Catalog and verified installer for OSCLinux themes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY = "IFN3T/OSCLinux"
MANIFEST_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/themes/manifest.json"
PACKAGE_BASE = f"https://raw.githubusercontent.com/{REPOSITORY}/main/themes/packages"
THEME_ROOT = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "osclinux" / "themes"
LOCAL_MANIFEST = Path(__file__).resolve().parent.parent / "themes" / "manifest.json"
LOCAL_PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "themes" / "packages"
BASE_THEME_ID = "base"
BASE_THEME_VERSION = "1.0.0"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
COLOR_TOKENS = {
    "window_bg", "window_text", "sidebar_bg", "topbar_bg", "panel_bg", "card_bg", "preview_bg",
    "bubble_bg", "bubble_border", "text_primary", "text_title", "text_page_title", "text_muted",
    "text_secondary", "preview_text", "preview_hint", "border", "border_strong", "button_bg",
    "button_hover", "button_border", "button_hover_border", "button_text", "primary_bg",
    "primary_hover", "primary_border", "primary_text", "danger_text", "danger_bg", "success_bg",
    "success_hover", "success_border", "success_text", "nav_text", "nav_active_bg", "nav_active_text", "nav_hover_bg",
    "input_bg", "input_border", "input_text", "input_focus", "selection_bg", "check_bg", "check_border",
    "check_active", "check_active_border", "radio_active", "radio_center", "scroll_handle", "scroll_border",
    "scroll_hover", "scroll_hover_border", "timeline_selected", "timeline_selected_border", "slider_track",
    "slider_handle", "status_border", "status_text", "accent", "timeline_bg", "timeline_tick",
    "timeline_guide", "timeline_text", "timeline_secondary", "timeline_block1", "timeline_block2",
    "timeline_block3", "timeline_block4", "timeline_block5", "timeline_border",
}
SHAPE_LIMITS = {
    "button_radius": (0, 24), "panel_radius": (0, 28), "card_radius": (0, 24),
    "input_radius": (0, 20), "control_radius": (0, 12), "button_padding_y": (4, 18),
    "button_padding_x": (6, 28), "timeline_radius": (0, 20), "bubble_radius": (0, 28),
    "icon_radius": (0, 40),
}
DEFAULT_SHAPE = {
    "button_radius": 7, "panel_radius": 10, "card_radius": 10, "input_radius": 6,
    "control_radius": 4, "button_padding_y": 9, "button_padding_x": 13, "timeline_radius": 7,
    "bubble_radius": 12, "icon_radius": 20,
}
LEGACY_COLOR_VALUES = {"#0d1425", "#0a1120", "#111c31", "#0c172a", "#dce7ff", "#f2f6ff", "#ecf2ff",
    "#8fa6ce", "#b4c5e7", "#1a2a47", "#1a2944", "#263a60", "#2d4266", "#587df7", "#15233c",
    "#334ff0", "#536bff", "#4560ff", "#16834f", "#22b970", "#1ba862", "#3a2033", "#ff9eae",
    "#20365d", "#8fb4ff", "#293d60", "#50668c", "#405bfa", "#7387ff", "#526aff", "#b8c4ff",
    "#2c4167", "#3a5685", "#4969a3", "#6688ca", "#263a5b", "#1b3157", "#5974ff", "#9db5dd",
    "#1c2a45", "#283a5a", "#91a8ce", "#718eff", "#b8c8e6", "#263d70", "#1c5360", "#593664",
    "#61501f", "#244e3b"}


class ThemeStoreError(RuntimeError):
    pass


def _fresh_url(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}_osclinux={time.time_ns()}"


class ThemeStore:
    def __init__(self, root: Path = THEME_ROOT) -> None:
        self.root = root

    def fetch_catalog(self) -> tuple[list[dict[str, Any]], bool]:
        request = urllib.request.Request(
            _fresh_url(MANIFEST_URL),
            headers={"User-Agent": "OSCLinux-ThemeStore/1", "Accept": "application/json", "Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                _require_raw_github(response.geturl(), "Hôte du catalogue non autorisé.")
                payload = json.loads(response.read(1_000_000).decode("utf-8"))
            return _validate_manifest(payload), True
        except (OSError, urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, ThemeStoreError):
            try:
                payload = json.loads(LOCAL_MANIFEST.read_text(encoding="utf-8"))
                return _validate_manifest(payload), False
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ThemeStoreError) as exc:
                raise ThemeStoreError(f"Catalogue distant indisponible et catalogue local invalide : {exc}") from exc

    def installed_versions(self) -> dict[str, str]:
        versions = {BASE_THEME_ID: BASE_THEME_VERSION}
        if not self.root.is_dir():
            return versions
        for metadata_file in self.root.glob("*/installed.json"):
            try:
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                theme_id = metadata_file.parent.name
                if _ID_RE.fullmatch(theme_id) and (metadata_file.parent / "theme.json").is_file():
                    versions[theme_id] = str(metadata["version"])
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return versions

    def install(self, entry: dict[str, Any]) -> None:
        theme_id = _validate_entry(entry)
        if theme_id == BASE_THEME_ID:
            raise ThemeStoreError("Le thème de base est déjà installé.")
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / theme_id
        if destination.exists():
            raise ThemeStoreError("Le thème est déjà installé.")
        self._download_and_install(entry, destination)

    def update(self, entry: dict[str, Any]) -> None:
        theme_id = _validate_entry(entry)
        if theme_id == BASE_THEME_ID:
            raise ThemeStoreError("Le thème de base ne peut pas être mis à jour.")
        destination = self.root / theme_id
        if not (destination / "theme.json").is_file():
            raise ThemeStoreError("Le thème n’est pas installé.")
        self._download_and_install(entry, destination, replace=True)

    def uninstall(self, theme_id: str) -> None:
        if not _ID_RE.fullmatch(theme_id) or theme_id == BASE_THEME_ID:
            raise ThemeStoreError("Le thème de base ne peut pas être supprimé.")
        destination = (self.root / theme_id).resolve()
        if self.root.resolve() not in destination.parents or (self.root / theme_id).is_symlink():
            raise ThemeStoreError("Chemin de thème invalide.")
        if destination.exists():
            shutil.rmtree(destination)

    def palette(self, theme_id: str) -> dict[str, str]:
        return self.configuration(theme_id)["colors"]

    def configuration(self, theme_id: str) -> dict[str, Any]:
        if theme_id == BASE_THEME_ID:
            return {"schema_version": 2, "colors": {}, "shape": dict(DEFAULT_SHAPE)}
        if not _ID_RE.fullmatch(theme_id):
            raise ThemeStoreError("Identifiant de thème invalide.")
        path = self.root / theme_id / "theme.json"
        if path.is_symlink() or not path.is_file() or self.root.resolve() not in path.resolve().parents:
            raise ThemeStoreError("Le fichier du thème installé est absent ou invalide.")
        try:
            return _validate_package(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ThemeStoreError(f"Impossible de lire le thème : {exc}") from exc

    def bundled_palette(self, theme_id: str) -> dict[str, str]:
        return self.bundled_configuration(theme_id)["colors"]

    def bundled_configuration(self, theme_id: str) -> dict[str, Any]:
        """Read a bundled theme configuration, including when a legacy install is present."""
        if not _ID_RE.fullmatch(theme_id):
            raise ThemeStoreError("Identifiant de thème invalide.")
        path = LOCAL_PACKAGE_ROOT / f"{theme_id}.json"
        try:
            return _validate_package(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ThemeStoreError(f"Impossible de lire le thème fourni : {exc}") from exc

    def _download_and_install(self, entry: dict[str, Any], destination: Path, *, replace: bool = False) -> None:
        theme_id = _validate_entry(entry)
        url = f"{PACKAGE_BASE}/{theme_id}.json"
        request = urllib.request.Request(
            _fresh_url(url),
            headers={"User-Agent": "OSCLinux-ThemeStore/1", "Accept": "application/json", "Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        package: bytes | None = None
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                _require_raw_github(response.geturl(), "Redirection vers un hôte interdit.")
                package = response.read(128_000 + 1)
        except (urllib.error.URLError, TimeoutError, OSError):
            local_package = LOCAL_PACKAGE_ROOT / f"{theme_id}.json"
            if local_package.is_file():
                package = local_package.read_bytes()
        if package is None:
            raise ThemeStoreError("Téléchargement du thème impossible.")
        if len(package) > 128_000:
            raise ThemeStoreError("Le fichier du thème dépasse la limite autorisée.")
        if hashlib.sha256(package).hexdigest() != entry["sha256"]:
            raise ThemeStoreError("L’empreinte SHA-256 du thème ne correspond pas au catalogue.")
        try:
            _validate_package(json.loads(package.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, ThemeStoreError) as exc:
            raise ThemeStoreError(f"Le fichier du thème est invalide : {exc}") from exc

        temporary = Path(tempfile.mkdtemp(prefix=f".{theme_id}-", dir=self.root))
        try:
            (temporary / "theme.json").write_bytes(package)
            metadata = {"id": theme_id, "version": entry["version"], "name": entry["name"], "author": entry["author"]}
            (temporary / "installed.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if replace:
                backup = destination.with_name(f".{theme_id}-backup")
                if backup.exists():
                    shutil.rmtree(backup)
                os.replace(destination, backup)
                try:
                    os.replace(temporary, destination)
                except Exception:
                    os.replace(backup, destination)
                    raise
                shutil.rmtree(backup, ignore_errors=True)
            else:
                os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)


def _validate_manifest(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("themes"), list):
        raise ThemeStoreError("Format du manifeste de thèmes non reconnu.")
    entries = [_validate_entry(item) and item for item in payload["themes"]]
    ids = [item["id"] for item in entries]
    if len(ids) != len(set(ids)) or BASE_THEME_ID in ids:
        raise ThemeStoreError("Le catalogue contient des identifiants en double ou réservés.")
    return entries


def _validate_entry(entry: Any) -> str:
    if not isinstance(entry, dict):
        raise ThemeStoreError("Entrée de thème invalide.")
    theme_id = entry.get("id")
    if not isinstance(theme_id, str) or not _ID_RE.fullmatch(theme_id) or theme_id == BASE_THEME_ID:
        raise ThemeStoreError("Identifiant de thème invalide ou réservé.")
    for field in ("name", "description", "author", "version"):
        if not isinstance(entry.get(field), str) or not entry[field].strip() or len(entry[field]) > 240:
            raise ThemeStoreError(f"Champ {field} invalide pour {theme_id}.")
    if not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", entry["version"]):
        raise ThemeStoreError(f"Version invalide pour {theme_id}.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))):
        raise ThemeStoreError(f"Empreinte SHA-256 absente ou invalide pour {theme_id}.")
    return theme_id


def _validate_package(package: Any) -> dict[str, Any]:
    if not isinstance(package, dict) or package.get("schema_version") not in {1, 2}:
        raise ThemeStoreError("Format du fichier de thème non reconnu.")
    version = package["schema_version"]
    colors = package.get("colors")
    if not isinstance(colors, dict) or len(colors) > 100:
        raise ThemeStoreError("Palette du thème invalide.")
    for token, color in colors.items():
        allowed = token in LEGACY_COLOR_VALUES if version == 1 else token in COLOR_TOKENS
        if not allowed or not isinstance(color, str) or not _COLOR_RE.fullmatch(color):
            raise ThemeStoreError("La palette contient une couleur ou un jeton interdit.")
    if version == 1:
        return {"schema_version": 1, "colors": colors, "shape": dict(DEFAULT_SHAPE)}

    shape = package.get("shape", {})
    if not isinstance(shape, dict) or set(shape) - set(SHAPE_LIMITS):
        raise ThemeStoreError("Configuration des formes invalide.")
    normalized_shape = dict(DEFAULT_SHAPE)
    for field, value in shape.items():
        minimum, maximum = SHAPE_LIMITS[field]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ThemeStoreError(f"Valeur de forme invalide : {field}.")
        normalized_shape[field] = value
    return {"schema_version": 2, "colors": colors, "shape": normalized_shape}


def _require_raw_github(url: str, message: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ThemeStoreError(message)
