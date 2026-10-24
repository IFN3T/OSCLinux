"""Central module catalog and verified install/update manager."""

from __future__ import annotations

import hashlib
import importlib.util
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
MANIFEST_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/modules/manifest.json"
PACKAGE_BASE = f"https://raw.githubusercontent.com/{REPOSITORY}/main/modules/packages"
MODULE_ROOT = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "osclinux" / "modules"
LOCAL_MANIFEST = Path(__file__).resolve().parent.parent / "modules" / "manifest.json"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ModuleStoreError(RuntimeError):
    pass


def _fresh_url(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}_osclinux={time.time_ns()}"


class ModuleStore:
    def __init__(self, root: Path = MODULE_ROOT) -> None:
        self.root = root
        self._loaded_modules: dict[str, Any] = {}

    def fetch_catalog(self) -> tuple[list[dict[str, Any]], bool]:
        request = urllib.request.Request(
            _fresh_url(MANIFEST_URL),
            headers={"User-Agent": "OSCLinux-ModuleStore/1", "Accept": "application/json", "Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                _require_raw_github(response.geturl(), "Hôte du catalogue non autorisé.")
                payload = json.loads(response.read(1_000_000).decode("utf-8"))
            return _validate_manifest(payload), True
        except (OSError, urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, ModuleStoreError):
            try:
                payload = json.loads(LOCAL_MANIFEST.read_text(encoding="utf-8"))
                return _validate_manifest(payload), False
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ModuleStoreError) as exc:
                raise ModuleStoreError(f"Catalogue distant indisponible et catalogue local invalide : {exc}") from exc

    def installed_versions(self) -> dict[str, str]:
        versions: dict[str, str] = {}
        if not self.root.is_dir():
            return versions
        for metadata_file in self.root.glob("*/installed.json"):
            try:
                payload = json.loads(metadata_file.read_text(encoding="utf-8"))
                module_id = metadata_file.parent.name
                if _ID_RE.fullmatch(module_id) and (metadata_file.parent / "module.py").is_file():
                    versions[module_id] = str(payload["version"])
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return versions

    def install(self, entry: dict[str, Any]) -> None:
        module_id = _validate_entry(entry)
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / module_id
        if destination.exists():
            raise ModuleStoreError("Le module est déjà installé.")
        self._download_and_install(entry, destination)

    def update(self, entry: dict[str, Any]) -> None:
        module_id = _validate_entry(entry)
        destination = self.root / module_id
        if not (destination / "module.py").is_file():
            raise ModuleStoreError("Le module n’est pas installé.")
        self._download_and_install(entry, destination, replace=True)

    def uninstall(self, module_id: str) -> None:
        if not _ID_RE.fullmatch(module_id):
            raise ModuleStoreError("Identifiant de module invalide.")
        destination = (self.root / module_id).resolve()
        if self.root.resolve() not in destination.parents:
            raise ModuleStoreError("Chemin de module hors du dossier autorisé.")
        if (self.root / module_id).is_symlink():
            raise ModuleStoreError("Un lien symbolique de module ne peut pas être supprimé.")
        if destination.exists():
            shutil.rmtree(destination)
        self._loaded_modules.pop(module_id, None)

    def load_text(self, module_id: str, options: dict[str, Any]) -> str:
        if not _ID_RE.fullmatch(module_id):
            raise ModuleStoreError("Identifiant de module invalide.")
        path = self.root / module_id / "module.py"
        if path.is_symlink() or not path.is_file() or self.root.resolve() not in path.resolve().parents:
            raise ModuleStoreError("Le fichier du module installé est absent ou invalide.")
        loaded = self._loaded_modules.get(module_id)
        if loaded is None:
            spec = importlib.util.spec_from_file_location(f"osclinux_user_module_{module_id}", path)
            if spec is None or spec.loader is None:
                raise ModuleStoreError("Impossible de charger le module.")
            loaded = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loaded)
            self._loaded_modules[module_id] = loaded
        entrypoint = getattr(loaded, "get_text", None)
        if not callable(entrypoint):
            raise ModuleStoreError("Le module n’expose pas de fonction get_text().")
        result = entrypoint(options)
        if not isinstance(result, str):
            raise ModuleStoreError("Le module a renvoyé une valeur invalide.")
        return result

    def _download_and_install(self, entry: dict[str, Any], destination: Path, *, replace: bool = False) -> None:
        module_id = _validate_entry(entry)
        url = f"{PACKAGE_BASE}/{module_id}.py"
        request = urllib.request.Request(
            _fresh_url(url),
            headers={"User-Agent": "OSCLinux-ModuleStore/1", "Accept": "text/plain", "Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                _require_raw_github(response.geturl(), "Redirection vers un hôte interdit.")
                package = response.read(2_000_000 + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModuleStoreError(f"Téléchargement du module impossible : {exc}") from exc
        if len(package) > 2_000_000:
            raise ModuleStoreError("Le fichier du module dépasse la limite autorisée.")
        if hashlib.sha256(package).hexdigest() != entry["sha256"]:
            raise ModuleStoreError("L’empreinte SHA-256 du module ne correspond pas au catalogue.")

        temporary = Path(tempfile.mkdtemp(prefix=f".{module_id}-", dir=self.root))
        try:
            (temporary / "module.py").write_bytes(package)
            metadata = {"id": module_id, "version": entry["version"], "name": entry["name"], "author": entry["author"]}
            (temporary / "installed.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if replace:
                backup = destination.with_name(f".{module_id}-backup")
                if backup.exists():
                    shutil.rmtree(backup)
                os.replace(destination, backup)
                try:
                    os.replace(temporary, destination)
                except Exception:
                    os.replace(backup, destination)
                    raise
                shutil.rmtree(backup, ignore_errors=True)
                self._loaded_modules.pop(module_id, None)
            else:
                os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)


def _validate_manifest(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("modules"), list):
        raise ModuleStoreError("Format du manifeste non reconnu.")
    entries = [_validate_entry(item) and item for item in payload["modules"]]
    ids = [item["id"] for item in entries]
    if len(ids) != len(set(ids)):
        raise ModuleStoreError("Le manifeste contient des identifiants en double.")
    return entries


def _validate_entry(entry: Any) -> str:
    if not isinstance(entry, dict):
        raise ModuleStoreError("Entrée de module invalide.")
    if "update_url" in entry:
        raise ModuleStoreError("Le champ update_url n’est pas pris en charge dans le manifeste.")
    module_id = entry.get("id")
    if not isinstance(module_id, str) or not _ID_RE.fullmatch(module_id):
        raise ModuleStoreError("Identifiant de module invalide.")
    for field in ("name", "description", "author", "version"):
        if not isinstance(entry.get(field), str) or not entry[field].strip() or len(entry[field]) > 240:
            raise ModuleStoreError(f"Champ {field} invalide pour {module_id}.")
    if not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", entry["version"]):
        raise ModuleStoreError(f"Version invalide pour {module_id}.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))):
        raise ModuleStoreError(f"Empreinte SHA-256 absente ou invalide pour {module_id}.")
    schema = entry.get("settings", [])
    if not isinstance(schema, list) or len(schema) > 30:
        raise ModuleStoreError(f"Réglages invalides pour {module_id}.")
    for setting in schema:
        if not isinstance(setting, dict) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", str(setting.get("key", ""))):
            raise ModuleStoreError(f"Champ de réglage invalide pour {module_id}.")
        if setting.get("type") not in {"text", "boolean", "choice", "number", "player"} or not isinstance(setting.get("label"), str):
            raise ModuleStoreError(f"Type de réglage invalide pour {module_id}.")
        if setting["type"] == "choice" and (not isinstance(setting.get("choices"), list) or not setting["choices"]):
            raise ModuleStoreError(f"Choix invalide pour {module_id}.")
    return module_id


def _require_raw_github(url: str, message: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ModuleStoreError(message)
