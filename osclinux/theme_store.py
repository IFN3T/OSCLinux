"""Catalog and verified installer for OSCLinux themes."""

from __future__ import annotations

import hashlib
import json
import math
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

from PySide6.QtGui import QImageReader

REPOSITORY = "IFN3T/OSCLinux"
MANIFEST_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/themes/manifest.json"
PACKAGE_BASE = f"https://raw.githubusercontent.com/{REPOSITORY}/main/themes/packages"
THEME_ROOT = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "osclinux" / "themes"
LOCAL_MANIFEST = Path(__file__).resolve().parent.parent / "themes" / "manifest.json"
LOCAL_PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "themes" / "packages"
BASE_THEME_ID = "base"
BASE_THEME_VERSION = "1.0.0"
LIGHT_THEME_ID = "light"
LIGHT_THEME_VERSION = "1.1.0"
BUILTIN_THEME_VERSIONS = {BASE_THEME_ID: BASE_THEME_VERSION, LIGHT_THEME_ID: LIGHT_THEME_VERSION}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_ASSET_NAME_RE = re.compile(r"^(?:background\.(?:png|jpe?g|webp|gif|webm)|icon-[a-z0-9_-]{1,32}\.(?:png|webp)|texture-[a-z0-9_-]{1,32}\.(?:png|jpe?g|webp))$", re.IGNORECASE)
_BACKGROUND_ASSET_RE = re.compile(r"^background\.(?:png|jpe?g|webp|gif|webm)$", re.IGNORECASE)
_ICON_ASSET_RE = re.compile(r"^icon-[a-z0-9_-]{1,32}\.(?:png|webp)$", re.IGNORECASE)
_TEXTURE_ASSET_RE = re.compile(r"^texture-[a-z0-9_-]{1,32}\.(?:png|jpe?g|webp)$", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_BACKGROUND_BYTES = 64 * 1024 * 1024
MAX_ICON_BYTES = 512 * 1024
MAX_TEXTURE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_DIMENSION = 8192
MAX_ANIMATION_FRAMES = 300
MAX_ANIMATION_TOTAL_PIXELS = 64_000_000
BACKGROUND_FORMATS = {"png", "jpeg", "webp", "gif"}
PATTERN_STYLES = {"none", "circuit", "pixel", "sakura"}
ICON_IDS = {"brand", "modules", "timeline", "osc", "themes", "settings", "journal", "audio_player", "system", "temperatures", "weather", "clock", "custom"}
TEXTURE_IDS = {"panel", "card", "sidebar", "topbar", "button"}
BORDER_STYLES = {"solid", "dashed", "dotted", "double", "groove", "ridge", "inset", "outset"}
ICON_CORNER_STYLES = {"square", "rounded", "circle"}
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
            remote_entries = _validate_manifest(payload)
            # A source checkout can safely preview its local theme packages before they are published.
            try:
                local_payload = json.loads(LOCAL_MANIFEST.read_text(encoding="utf-8"))
                local_entries = _validate_manifest(local_payload)
                merged = {entry["id"]: entry for entry in remote_entries}
                merged.update({entry["id"]: entry for entry in local_entries if (LOCAL_PACKAGE_ROOT / f"{entry['id']}.json").is_file()})
                return list(merged.values()), True
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ThemeStoreError):
                return remote_entries, True
        except (OSError, urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, ThemeStoreError):
            try:
                payload = json.loads(LOCAL_MANIFEST.read_text(encoding="utf-8"))
                return _validate_manifest(payload), False
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ThemeStoreError) as exc:
                raise ThemeStoreError(f"Catalogue distant indisponible et catalogue local invalide : {exc}") from exc

    def installed_versions(self) -> dict[str, str]:
        versions = dict(BUILTIN_THEME_VERSIONS)
        if not self.root.is_dir():
            return versions
        for metadata_file in self.root.glob("*/installed.json"):
            try:
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                theme_id = metadata_file.parent.name
                if theme_id not in BUILTIN_THEME_VERSIONS and _ID_RE.fullmatch(theme_id) and (metadata_file.parent / "theme.json").is_file():
                    versions[theme_id] = str(metadata["version"])
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return versions

    def install(self, entry: dict[str, Any]) -> None:
        theme_id = _validate_entry(entry)
        if theme_id in BUILTIN_THEME_VERSIONS:
            raise ThemeStoreError("Ce thème est déjà intégré et ne peut pas être réinstallé.")
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / theme_id
        if destination.exists():
            raise ThemeStoreError("Le thème est déjà installé.")
        self._download_and_install(entry, destination)

    def update(self, entry: dict[str, Any]) -> None:
        theme_id = _validate_entry(entry)
        if theme_id in BUILTIN_THEME_VERSIONS:
            raise ThemeStoreError("Un thème intégré ne peut pas être mis à jour depuis le catalogue.")
        destination = self.root / theme_id
        if not (destination / "theme.json").is_file():
            raise ThemeStoreError("Le thème n’est pas installé.")
        self._download_and_install(entry, destination, replace=True)

    def uninstall(self, theme_id: str) -> None:
        if not _ID_RE.fullmatch(theme_id) or theme_id in BUILTIN_THEME_VERSIONS:
            raise ThemeStoreError("Les thèmes intégrés ne peuvent pas être supprimés.")
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
        if theme_id == LIGHT_THEME_ID:
            return self.bundled_configuration(LIGHT_THEME_ID)
        if not _ID_RE.fullmatch(theme_id):
            raise ThemeStoreError("Identifiant de thème invalide.")
        path = self.root / theme_id / "theme.json"
        if path.is_symlink() or not path.is_file() or self.root.resolve() not in path.resolve().parents:
            raise ThemeStoreError("Le fichier du thème installé est absent ou invalide.")
        try:
            return _validate_package(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ThemeStoreError(f"Impossible de lire le thème : {exc}") from exc

    def background_path(self, theme_id: str, configuration: dict[str, Any]) -> Path | None:
        background = configuration.get("background")
        if not background:
            return None
        asset_name = background.get("asset")
        if not isinstance(asset_name, str) or not _BACKGROUND_ASSET_RE.fullmatch(asset_name):
            raise ThemeStoreError("Nom d’image de fond invalide.")
        return self.asset_path(theme_id, asset_name)

    def asset_path(self, theme_id: str, asset_name: str) -> Path | None:
        """Return a verified in-theme asset path (bundled or installed)."""
        if not _ID_RE.fullmatch(theme_id) or not isinstance(asset_name, str) or not _ASSET_NAME_RE.fullmatch(asset_name):
            raise ThemeStoreError("Nom de ressource de thème invalide.")
        theme_dir = self.root / theme_id
        # During development and for bundled themes, use assets shipped beside the local package.
        bundled_assets = LOCAL_PACKAGE_ROOT.parent / "assets" / theme_id
        candidates = (theme_dir / "assets" / asset_name, bundled_assets / asset_name)
        path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        try:
            resolved = path.resolve(strict=True)
            assets_dir = path.parent
            if (
                theme_dir.is_symlink()
                or path.is_symlink()
                or assets_dir.is_symlink()
                or not any(root.resolve() in resolved.parents for root in (theme_dir, bundled_assets))
                or not resolved.is_file()
            ):
                raise ThemeStoreError("Ressource hors du dossier du thème.")
        except OSError as exc:
            raise ThemeStoreError("Ressource de thème introuvable.") from exc
        _validate_theme_asset(resolved)
        return resolved

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
        local_package = LOCAL_PACKAGE_ROOT / f"{theme_id}.json"
        if local_package.is_file():
            with local_package.open("rb") as stream:
                candidate = stream.read(128_001)
            if hashlib.sha256(candidate).hexdigest() == entry["sha256"]:
                package = candidate
        if package is None:
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    _require_raw_github(response.geturl(), "Redirection vers un hôte interdit.")
                    package = response.read(128_000 + 1)
            except (urllib.error.URLError, TimeoutError, OSError):
                if local_package.is_file():
                    with local_package.open("rb") as stream:
                        package = stream.read(128_001)
        if package is None:
            raise ThemeStoreError("Téléchargement du thème impossible.")
        if len(package) > 128_000:
            raise ThemeStoreError("Le fichier du thème dépasse la limite autorisée.")
        if hashlib.sha256(package).hexdigest() != entry["sha256"]:
            raise ThemeStoreError("L’empreinte SHA-256 du thème ne correspond pas au catalogue.")
        try:
            configuration = _validate_package(json.loads(package.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, ThemeStoreError) as exc:
            raise ThemeStoreError(f"Le fichier du thème est invalide : {exc}") from exc

        assets = entry.get("assets", [])
        asset_by_name = {asset["name"]: asset for asset in assets}
        references = _package_asset_references(configuration)
        if set(asset_by_name) != references:
            raise ThemeStoreError("Les fichiers déclarés dans le catalogue ne correspondent pas aux références du thème.")

        temporary = Path(tempfile.mkdtemp(prefix=f".{theme_id}-", dir=self.root))
        try:
            (temporary / "theme.json").write_bytes(package)
            if assets:
                assets_dir = temporary / "assets"
                assets_dir.mkdir()
            total_bytes = 0
            for name in sorted(references):
                asset = asset_by_name[name]
                byte_limit = _asset_byte_limit(name)
                request = urllib.request.Request(
                    asset["url"],
                    headers={"User-Agent": "OSCLinux-ThemeStore/1", "Accept": "image/png,image/jpeg,image/webp,image/gif,video/webm", "Cache-Control": "no-store"},
                )
                image_bytes = None
                try:
                    expected_path = f"/{REPOSITORY}/main/themes/assets/{theme_id}/{name}"
                    opener = urllib.request.build_opener(_GitHubAssetRedirectHandler(expected_path))
                    with opener.open(request, timeout=10) as response:
                        _require_github_asset(response.geturl(), "Redirection vers une URL de texture non autorisée.")
                        image_bytes = response.read(byte_limit + 1)
                except (urllib.error.URLError, TimeoutError, OSError):
                    image_bytes = None
                local_asset = LOCAL_PACKAGE_ROOT.parent / "assets" / theme_id / name
                if image_bytes is None or hashlib.sha256(image_bytes).hexdigest() != asset["sha256"]:
                    if local_asset.is_file():
                        with local_asset.open("rb") as stream:
                            image_bytes = stream.read(byte_limit + 1)
                    else:
                        raise ThemeStoreError(f"Téléchargement de la ressource {name} impossible.")
                if len(image_bytes) > byte_limit:
                    raise ThemeStoreError(f"La ressource {name} dépasse sa limite de taille.")
                total_bytes += len(image_bytes)
                if total_bytes > MAX_BACKGROUND_BYTES:
                    raise ThemeStoreError("Les ressources du thème dépassent la limite totale de 64 Mio.")
                if hashlib.sha256(image_bytes).hexdigest() != asset["sha256"]:
                    raise ThemeStoreError("L’empreinte SHA-256 de l’image ne correspond pas au catalogue.")
                image_path = assets_dir / name
                image_path.write_bytes(image_bytes)
                _validate_theme_asset(image_path)
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
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1 or not isinstance(payload.get("themes"), list):
        raise ThemeStoreError("Format du manifeste de thèmes non reconnu.")
    entries = [_validate_entry(item) and item for item in payload["themes"]]
    ids = [item["id"] for item in entries]
    if len(ids) != len(set(ids)) or set(ids) & set(BUILTIN_THEME_VERSIONS):
        raise ThemeStoreError("Le catalogue contient des identifiants en double ou réservés.")
    return entries


def _validate_entry(entry: Any) -> str:
    if not isinstance(entry, dict):
        raise ThemeStoreError("Entrée de thème invalide.")
    if set(entry) - {"id", "name", "description", "author", "version", "sha256", "assets"}:
        raise ThemeStoreError("L’entrée du catalogue contient des champs non autorisés.")
    theme_id = entry.get("id")
    if not isinstance(theme_id, str) or not _ID_RE.fullmatch(theme_id) or theme_id in BUILTIN_THEME_VERSIONS:
        raise ThemeStoreError("Identifiant de thème invalide ou réservé.")
    for field in ("name", "description", "author", "version"):
        if not isinstance(entry.get(field), str) or not entry[field].strip() or len(entry[field]) > 240:
            raise ThemeStoreError(f"Champ {field} invalide pour {theme_id}.")
    if not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", entry["version"]):
        raise ThemeStoreError(f"Version invalide pour {theme_id}.")
    if not _SHA256_RE.fullmatch(str(entry.get("sha256", ""))):
        raise ThemeStoreError(f"Empreinte SHA-256 absente ou invalide pour {theme_id}.")
    assets = entry.get("assets", [])
    if not isinstance(assets, list) or len(assets) > 64:
        raise ThemeStoreError(f"Liste de fichiers de thème invalide pour {theme_id}.")
    seen_assets = set()
    for asset in assets:
        if not isinstance(asset, dict) or set(asset) != {"name", "url", "sha256"}:
            raise ThemeStoreError(f"Déclaration d’image invalide pour {theme_id}.")
        name = asset.get("name")
        if not isinstance(name, str) or not _ASSET_NAME_RE.fullmatch(name) or name in seen_assets:
            raise ThemeStoreError(f"Nom d’image interdit pour {theme_id}.")
        _validate_github_asset_url(asset.get("url"))
        expected_path = f"/{REPOSITORY}/main/themes/assets/{theme_id}/{name}"
        if urllib.parse.urlsplit(asset["url"]).path != expected_path:
            raise ThemeStoreError(f"L’URL de la ressource doit pointer vers le dossier GitHub du thème {theme_id}.")
        if not isinstance(asset.get("sha256"), str) or not _SHA256_RE.fullmatch(asset["sha256"]):
            raise ThemeStoreError(f"Empreinte d’image invalide pour {theme_id}.")
        seen_assets.add(name)
    return theme_id


def _validate_package(package: Any) -> dict[str, Any]:
    if not isinstance(package, dict) or type(package.get("schema_version")) is not int or package["schema_version"] not in {1, 2, 3}:
        raise ThemeStoreError("Format du fichier de thème non reconnu.")
    version = package["schema_version"]
    allowed_package_fields = {1: {"schema_version", "colors"}, 2: {"schema_version", "colors", "shape"}, 3: {"schema_version", "colors", "shape", "background", "pattern", "visuals", "icons", "icon_drawings", "textures"}}
    if set(package) - allowed_package_fields[version]:
        raise ThemeStoreError("Le thème contient des champs non autorisés.")
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
    result = {"schema_version": version, "colors": colors, "shape": normalized_shape}
    if version == 3:
        result["visuals"] = _validate_visuals(package.get("visuals", {}), colors)
        result["icons"] = _validate_asset_map(package.get("icons", {}), ICON_IDS, _ICON_ASSET_RE, "icône")
        result["icon_drawings"] = _validate_icon_definitions(package.get("icon_drawings", {}))
        result["textures"] = _validate_asset_map(package.get("textures", {}), TEXTURE_IDS, _TEXTURE_ASSET_RE, "texture")
        background = package.get("background")
        if background is not None:
            allowed_fields = {"asset", "image_opacity", "fit", "overlay_color", "overlay_opacity"}
            if not isinstance(background, dict) or set(background) - allowed_fields:
                raise ThemeStoreError("Configuration de l’image de fond invalide.")
            asset = background.get("asset")
            if not isinstance(asset, str) or not _BACKGROUND_ASSET_RE.fullmatch(asset):
                raise ThemeStoreError("Fichier d’image de fond interdit.")
            image_opacity = background.get("image_opacity", 100)
            overlay_opacity = background.get("overlay_opacity", 35)
            fit = background.get("fit", "cover")
            overlay_color = background.get("overlay_color", "#000000")
            if isinstance(image_opacity, bool) or not isinstance(image_opacity, int) or not 0 <= image_opacity <= 100:
                raise ThemeStoreError("Opacité de l’image invalide.")
            if isinstance(overlay_opacity, bool) or not isinstance(overlay_opacity, int) or not 0 <= overlay_opacity <= 85:
                raise ThemeStoreError("Opacité du voile invalide.")
            if not isinstance(fit, str) or fit not in {"cover", "contain", "stretch"} or not isinstance(overlay_color, str) or not _COLOR_RE.fullmatch(overlay_color):
                raise ThemeStoreError("Rendu de l’image ou couleur du voile invalide.")
            result["background"] = {
                "asset": asset,
                "image_opacity": image_opacity,
                "fit": fit,
                "overlay_color": overlay_color,
                "overlay_opacity": overlay_opacity,
            }
        else:
            result["background"] = None

        pattern = package.get("pattern", {})
        if not isinstance(pattern, dict) or set(pattern) - {"style", "opacity", "color"}:
            raise ThemeStoreError("Configuration du motif décoratif invalide.")
        style = pattern.get("style", "none")
        opacity = pattern.get("opacity", 12)
        color = pattern.get("color", colors.get("accent", "#5974ff"))
        if not isinstance(style, str) or style not in PATTERN_STYLES:
            raise ThemeStoreError("Motif décoratif non autorisé.")
        if isinstance(opacity, bool) or not isinstance(opacity, int) or not 0 <= opacity <= 30:
            raise ThemeStoreError("Opacité du motif décoratif invalide.")
        if not isinstance(color, str) or not _COLOR_RE.fullmatch(color):
            raise ThemeStoreError("Couleur du motif décoratif invalide.")
        result["pattern"] = {"style": style, "opacity": opacity, "color": color}
    return result


def _validate_asset_map(value: Any, allowed_ids: set[str], filename_pattern: re.Pattern, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > len(allowed_ids) or set(value) - allowed_ids:
        raise ThemeStoreError(f"Références de {label}s invalides.")
    normalized = {}
    for asset_id, filename in value.items():
        if not isinstance(filename, str) or not filename_pattern.fullmatch(filename):
            raise ThemeStoreError(f"Nom de fichier de {label} invalide pour {asset_id}.")
        normalized[asset_id] = filename
    return normalized


def _package_asset_references(configuration: dict[str, Any]) -> set[str]:
    references = set(configuration.get("icons", {}).values())
    references.update(configuration.get("textures", {}).values())
    background = configuration.get("background")
    if background:
        references.add(background["asset"])
    if len(references) > 64:
        raise ThemeStoreError("Le thème référence trop de fichiers.")
    return references


def _validate_visuals(visuals: Any, colors: dict[str, str]) -> dict[str, Any]:
    if not isinstance(visuals, dict) or set(visuals) - {"panel", "card", "button", "icon"}:
        raise ThemeStoreError("Réglages visuels de thème invalides.")
    result: dict[str, Any] = {}
    defaults = {
        "panel": {"border_width": 1, "border_style": "solid", "border_color": colors.get("border", "#263a5b"), "highlight_color": None},
        "card": {"border_width": 1, "border_style": "solid", "border_color": colors.get("border", "#263a5b"), "highlight_color": None},
        "button": {"border_width": 1, "border_style": "solid", "border_color": colors.get("button_border", "#2d4266"), "highlight_color": None},
    }
    surface_fields = {"border_width", "border_style", "border_color", "highlight_color"}
    for surface, default in defaults.items():
        config = visuals.get(surface, {})
        if not isinstance(config, dict) or set(config) - surface_fields:
            raise ThemeStoreError(f"Réglages de bordure invalides : {surface}.")
        normalized = dict(default)
        normalized.update(config)
        width = normalized["border_width"]
        style = normalized["border_style"]
        if isinstance(width, bool) or not isinstance(width, int) or not 0 <= width <= 4:
            raise ThemeStoreError(f"Épaisseur de bordure invalide : {surface}.")
        if not isinstance(style, str) or style not in BORDER_STYLES:
            raise ThemeStoreError(f"Style de bordure non autorisé : {surface}.")
        for color_field in ("border_color", "highlight_color"):
            color = normalized[color_field]
            if color is not None and (not isinstance(color, str) or not _COLOR_RE.fullmatch(color)):
                raise ThemeStoreError(f"Couleur de bordure invalide : {surface}.")
        result[surface] = normalized
    icon = visuals.get("icon", {})
    icon_fields = {"background_color", "border_color", "border_width", "corner_style", "stroke_width", "foreground_color", "secondary_color"}
    if not isinstance(icon, dict) or set(icon) - icon_fields:
        raise ThemeStoreError("Réglages du cadre des icônes invalides.")
    normalized_icon = {
        "background_color": colors.get("button_bg", "#1a2944"),
        "border_color": colors.get("accent", "#5974ff"),
        "border_width": 1,
        "corner_style": "rounded",
        "stroke_width": 2,
        "foreground_color": colors.get("accent", "#5974ff"),
        "secondary_color": colors.get("text_primary", "#dce7ff"),
    }
    normalized_icon.update(icon)
    for field in ("background_color", "border_color", "foreground_color", "secondary_color"):
        if not isinstance(normalized_icon[field], str) or not _COLOR_RE.fullmatch(normalized_icon[field]):
            raise ThemeStoreError(f"Couleur du cadre d’icône invalide : {field}.")
    for field, maximum in (("border_width", 4), ("stroke_width", 5)):
        value = normalized_icon[field]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
            raise ThemeStoreError(f"Valeur de style d’icône invalide : {field}.")
    if normalized_icon["corner_style"] not in ICON_CORNER_STYLES:
        raise ThemeStoreError("Forme du cadre d’icône non autorisée.")
    result["icon"] = normalized_icon
    return result


def _valid_point(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 32


def _validate_icon_definitions(icons: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(icons, dict) or len(icons) > len(ICON_IDS) or set(icons) - ICON_IDS:
        raise ThemeStoreError("Liste d’icônes de thème invalide.")
    normalized: dict[str, list[dict[str, Any]]] = {}
    total_shapes = 0
    for icon_id, shapes in icons.items():
        if not isinstance(shapes, list) or not shapes or len(shapes) > 18:
            raise ThemeStoreError(f"Définition de dessin invalide pour l’icône {icon_id}.")
        total_shapes += len(shapes)
        if total_shapes > 180:
            raise ThemeStoreError("Le thème dépasse la limite de primitives pour les icônes.")
        parsed_shapes = []
        for shape in shapes:
            if not isinstance(shape, dict) or shape.get("type") not in {"line", "rect", "ellipse", "polygon"}:
                raise ThemeStoreError(f"Primitive non autorisée dans l’icône {icon_id}.")
            kind = shape["type"]
            common = {"type", "fill", "stroke", "stroke_width"}
            required_by_type = {
                "line": {"x1", "y1", "x2", "y2", "color", "width"},
                "rect": {"x", "y", "width", "height"},
                "ellipse": {"x", "y", "width", "height"},
                "polygon": {"points"},
            }
            allowed = common | required_by_type[kind]
            if kind == "line":
                allowed = {"type", "x1", "y1", "x2", "y2", "color", "width"}
                if set(shape) != allowed or any(not _valid_point(shape[key]) for key in ("x1", "y1", "x2", "y2")):
                    raise ThemeStoreError(f"Coordonnées de ligne invalides dans l’icône {icon_id}.")
                if not isinstance(shape["color"], str) or not _COLOR_RE.fullmatch(shape["color"]):
                    raise ThemeStoreError(f"Couleur de ligne invalide dans l’icône {icon_id}.")
                if isinstance(shape["width"], bool) or not isinstance(shape["width"], (int, float)) or not math.isfinite(shape["width"]) or not 0 <= shape["width"] <= 5:
                    raise ThemeStoreError(f"Épaisseur de ligne invalide dans l’icône {icon_id}.")
            else:
                if set(shape) - allowed or not required_by_type[kind] <= set(shape):
                    raise ThemeStoreError(f"Champs de primitive invalides dans l’icône {icon_id}.")
                if kind in {"rect", "ellipse"}:
                    if any(not _valid_point(shape[key]) for key in ("x", "y", "width", "height")) or shape["width"] == 0 or shape["height"] == 0:
                        raise ThemeStoreError(f"Dimensions invalides dans l’icône {icon_id}.")
                if kind == "polygon":
                    points = shape["points"]
                    if not isinstance(points, list) or not 3 <= len(points) <= 16 or any(not isinstance(point, list) or len(point) != 2 or not all(_valid_point(coord) for coord in point) for point in points):
                        raise ThemeStoreError(f"Polygone invalide dans l’icône {icon_id}.")
                if shape.get("fill") is None and shape.get("stroke") is None:
                    raise ThemeStoreError(f"La primitive de l’icône {icon_id} doit avoir une couleur.")
                for field in ("fill", "stroke"):
                    value = shape.get(field)
                    if value is not None and (not isinstance(value, str) or not _COLOR_RE.fullmatch(value)):
                        raise ThemeStoreError(f"Couleur de primitive invalide dans l’icône {icon_id}.")
                stroke_width = shape.get("stroke_width", 1)
                if isinstance(stroke_width, bool) or not isinstance(stroke_width, (int, float)) or not math.isfinite(stroke_width) or not 0 <= stroke_width <= 5:
                    raise ThemeStoreError(f"Contour de primitive invalide dans l’icône {icon_id}.")
            parsed_shapes.append(shape)
        normalized[icon_id] = parsed_shapes
    return normalized


def _require_raw_github(url: str, message: str) -> None:
    try:
        parsed = urllib.parse.urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise ThemeStoreError(message) from exc
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com" or parsed.username or parsed.password or port not in (None, 443):
        raise ThemeStoreError(message)


def _validate_github_asset_url(url: Any) -> None:
    if not isinstance(url, str) or len(url) > 2048:
        raise ThemeStoreError("URL d’image invalide.")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ThemeStoreError("URL d’image invalide.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "raw.githubusercontent.com"
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
        or "\\" in parsed.path
        or not parsed.path.startswith("/")
        or any(part in {"", ".", ".."} for part in parsed.path.split("/")[1:])
        or not re.search(r"\.(?:png|jpe?g|webp|gif|webm)$", parsed.path, re.IGNORECASE)
    ):
        raise ThemeStoreError("Les textures doivent venir d’une URL HTTPS raw.githubusercontent.com sans paramètres.")


def _require_github_asset(url: str, message: str) -> None:
    try:
        _validate_github_asset_url(url)
    except ThemeStoreError as exc:
        raise ThemeStoreError(message) from exc


class _GitHubAssetRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, expected_path: str):
        super().__init__()
        self.expected_path = expected_path

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        _require_github_asset(new_url, "Redirection d’image hors de GitHub refusée.")
        parsed = urllib.parse.urlsplit(new_url)
        if parsed.path != self.expected_path or parsed.query:
            raise ThemeStoreError("Redirection vers un fichier du thème non autorisé.")
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def _asset_byte_limit(name: str) -> int:
    if _BACKGROUND_ASSET_RE.fullmatch(name):
        return MAX_BACKGROUND_BYTES
    if _ICON_ASSET_RE.fullmatch(name):
        return MAX_ICON_BYTES
    if _TEXTURE_ASSET_RE.fullmatch(name):
        return MAX_TEXTURE_BYTES
    raise ThemeStoreError("Type de ressource de thème non autorisé.")


def _validate_theme_asset(path: Path) -> None:
    if _BACKGROUND_ASSET_RE.fullmatch(path.name):
        _validate_background_image(path)
        return
    byte_limit = _asset_byte_limit(path.name)
    if path.is_symlink() or path.stat().st_size > byte_limit:
        raise ThemeStoreError(f"Fichier de ressource invalide ou trop volumineux : {path.name}.")
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image_format = bytes(reader.format()).decode("ascii", "ignore").lower()
    size = reader.size()
    allowed_formats = {"png", "webp"} if _ICON_ASSET_RE.fullmatch(path.name) else {"png", "jpeg", "webp"}
    if image_format not in allowed_formats or not size.isValid():
        raise ThemeStoreError(f"Format d’image interdit ou fichier illisible : {path.name}.")
    if size.width() > 2048 or size.height() > 2048 or size.width() * size.height() > 4_000_000:
        raise ThemeStoreError(f"Dimensions d’image trop grandes : {path.name}.")
    if reader.read().isNull():
        raise ThemeStoreError(f"Impossible de décoder l’image : {path.name}.")


def _validate_background_image(path: Path) -> None:
    if path.is_symlink() or path.stat().st_size > MAX_BACKGROUND_BYTES:
        raise ThemeStoreError("Fichier de texture invalide ou supérieur à 64 Mio.")
    if path.suffix.lower() == ".webm":
        # WebM is decoded by Qt Multimedia at runtime. Reject files without the
        # EBML container signature before passing a downloaded file to a decoder.
        with path.open("rb") as stream:
            if stream.read(4) != b"\x1a\x45\xdf\xa3":
                raise ThemeStoreError("Le fichier WebM n’a pas une signature EBML valide.")
        return
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image_format = bytes(reader.format()).decode("ascii", "ignore").lower()
    size = reader.size()
    if image_format not in BACKGROUND_FORMATS or not size.isValid():
        raise ThemeStoreError("Seules les images PNG, JPEG, WebP et GIF valides sont acceptées.")
    if size.width() > MAX_IMAGE_DIMENSION or size.height() > MAX_IMAGE_DIMENSION or size.width() * size.height() > MAX_IMAGE_PIXELS:
        raise ThemeStoreError("Les dimensions de l’image de fond dépassent la limite autorisée.")
    animated = reader.supportsAnimation()
    total_pixels = 0
    frame_count = 0
    while True:
        frame = reader.read()
        if frame.isNull():
            raise ThemeStoreError("Impossible de décoder une image de la texture.")
        frame_count += 1
        if animated and frame_count > MAX_ANIMATION_FRAMES:
            raise ThemeStoreError("L’animation dépasse la limite de 300 images.")
        total_pixels += frame.width() * frame.height()
        if total_pixels > MAX_ANIMATION_TOTAL_PIXELS:
            raise ThemeStoreError("L’animation dépasse la limite de décodage autorisée.")
        if not animated or not reader.jumpToNextImage():
            break
