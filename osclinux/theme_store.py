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

from PySide6.QtGui import QImageReader

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
_ASSET_NAME_RE = re.compile(r"^background\.(?:png|jpe?g|webp|gif|webm)$", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_BACKGROUND_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_DIMENSION = 8192
MAX_ANIMATION_FRAMES = 300
MAX_ANIMATION_TOTAL_PIXELS = 64_000_000
BACKGROUND_FORMATS = {"png", "jpeg", "webp", "gif"}
PATTERN_STYLES = {"none", "circuit", "pixel", "sakura"}
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

    def background_path(self, theme_id: str, configuration: dict[str, Any]) -> Path | None:
        background = configuration.get("background")
        if not background:
            return None
        asset_name = background.get("asset")
        if not isinstance(asset_name, str) or not _ASSET_NAME_RE.fullmatch(asset_name):
            raise ThemeStoreError("Nom d’image de fond invalide.")
        theme_dir = self.root / theme_id
        assets_dir = theme_dir / "assets"
        path = assets_dir / asset_name
        try:
            resolved = path.resolve(strict=True)
            if (
                theme_dir.is_symlink()
                or assets_dir.is_symlink()
                or path.is_symlink()
                or theme_dir.resolve() not in resolved.parents
                or not resolved.is_file()
            ):
                raise ThemeStoreError("Image de fond hors du dossier du thème.")
        except OSError as exc:
            raise ThemeStoreError("Image de fond du thème introuvable.") from exc
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
            configuration = _validate_package(json.loads(package.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, ThemeStoreError) as exc:
            raise ThemeStoreError(f"Le fichier du thème est invalide : {exc}") from exc

        assets = entry.get("assets", [])
        asset_by_name = {asset["name"]: asset for asset in assets}
        background = configuration.get("background")
        if background:
            if set(asset_by_name) != {background["asset"]}:
                raise ThemeStoreError("L’image de fond ne correspond pas aux fichiers déclarés dans le catalogue.")
        elif assets:
            raise ThemeStoreError("Le catalogue déclare un fichier que le thème n’utilise pas.")

        temporary = Path(tempfile.mkdtemp(prefix=f".{theme_id}-", dir=self.root))
        try:
            (temporary / "theme.json").write_bytes(package)
            if background:
                asset = asset_by_name[background["asset"]]
                request = urllib.request.Request(
                    asset["url"],
                    headers={"User-Agent": "OSCLinux-ThemeStore/1", "Accept": "image/png,image/jpeg,image/webp,image/gif,video/webm", "Cache-Control": "no-store"},
                )
                try:
                    opener = urllib.request.build_opener(_GitHubAssetRedirectHandler())
                    with opener.open(request, timeout=10) as response:
                        _require_github_asset(response.geturl(), "Redirection vers une URL de texture non autorisée.")
                        image_bytes = response.read(MAX_BACKGROUND_BYTES + 1)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    raise ThemeStoreError(f"Téléchargement de l’image du thème impossible : {exc}") from exc
                if len(image_bytes) > MAX_BACKGROUND_BYTES:
                    raise ThemeStoreError("La texture de fond dépasse la limite de 16 Mio.")
                if hashlib.sha256(image_bytes).hexdigest() != asset["sha256"]:
                    raise ThemeStoreError("L’empreinte SHA-256 de l’image ne correspond pas au catalogue.")
                assets_dir = temporary / "assets"
                assets_dir.mkdir()
                image_path = assets_dir / background["asset"]
                image_path.write_bytes(image_bytes)
                _validate_background_image(image_path)
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
    if len(ids) != len(set(ids)) or BASE_THEME_ID in ids:
        raise ThemeStoreError("Le catalogue contient des identifiants en double ou réservés.")
    return entries


def _validate_entry(entry: Any) -> str:
    if not isinstance(entry, dict):
        raise ThemeStoreError("Entrée de thème invalide.")
    if set(entry) - {"id", "name", "description", "author", "version", "sha256", "assets"}:
        raise ThemeStoreError("L’entrée du catalogue contient des champs non autorisés.")
    theme_id = entry.get("id")
    if not isinstance(theme_id, str) or not _ID_RE.fullmatch(theme_id) or theme_id == BASE_THEME_ID:
        raise ThemeStoreError("Identifiant de thème invalide ou réservé.")
    for field in ("name", "description", "author", "version"):
        if not isinstance(entry.get(field), str) or not entry[field].strip() or len(entry[field]) > 240:
            raise ThemeStoreError(f"Champ {field} invalide pour {theme_id}.")
    if not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", entry["version"]):
        raise ThemeStoreError(f"Version invalide pour {theme_id}.")
    if not _SHA256_RE.fullmatch(str(entry.get("sha256", ""))):
        raise ThemeStoreError(f"Empreinte SHA-256 absente ou invalide pour {theme_id}.")
    assets = entry.get("assets", [])
    if not isinstance(assets, list) or len(assets) > 1:
        raise ThemeStoreError(f"Liste de fichiers de thème invalide pour {theme_id}.")
    seen_assets = set()
    for asset in assets:
        if not isinstance(asset, dict) or set(asset) != {"name", "url", "sha256"}:
            raise ThemeStoreError(f"Déclaration d’image invalide pour {theme_id}.")
        name = asset.get("name")
        if not isinstance(name, str) or not _ASSET_NAME_RE.fullmatch(name) or name in seen_assets:
            raise ThemeStoreError(f"Nom d’image interdit pour {theme_id}.")
        _validate_github_asset_url(asset.get("url"))
        if urllib.parse.urlsplit(asset["url"]).path.rsplit("/", 1)[-1].lower() != name.lower():
            raise ThemeStoreError(f"Le nom de la texture et son URL ne correspondent pas pour {theme_id}.")
        if not isinstance(asset.get("sha256"), str) or not _SHA256_RE.fullmatch(asset["sha256"]):
            raise ThemeStoreError(f"Empreinte d’image invalide pour {theme_id}.")
        seen_assets.add(name)
    return theme_id


def _validate_package(package: Any) -> dict[str, Any]:
    if not isinstance(package, dict) or type(package.get("schema_version")) is not int or package["schema_version"] not in {1, 2, 3}:
        raise ThemeStoreError("Format du fichier de thème non reconnu.")
    version = package["schema_version"]
    allowed_package_fields = {1: {"schema_version", "colors"}, 2: {"schema_version", "colors", "shape"}, 3: {"schema_version", "colors", "shape", "background", "pattern"}}
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
        background = package.get("background")
        if background is not None:
            allowed_fields = {"asset", "image_opacity", "fit", "overlay_color", "overlay_opacity"}
            if not isinstance(background, dict) or set(background) - allowed_fields:
                raise ThemeStoreError("Configuration de l’image de fond invalide.")
            asset = background.get("asset")
            if not isinstance(asset, str) or not _ASSET_NAME_RE.fullmatch(asset):
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
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        _require_github_asset(new_url, "Redirection d’image hors de GitHub refusée.")
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def _validate_background_image(path: Path) -> None:
    if path.is_symlink() or path.stat().st_size > MAX_BACKGROUND_BYTES:
        raise ThemeStoreError("Fichier de texture invalide ou supérieur à 16 Mio.")
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
