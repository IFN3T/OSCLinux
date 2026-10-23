"""Secure, opt-in updater for the OSCLinux GitHub Releases channel.

The updater only checks and stages releases. The application should ask the
user before downloading and should apply a staged release on the next launch.
This keeps the running process from replacing its own code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_REPOSITORY = "IFN3T/OSCLinux"
MAX_RELEASE_BYTES = 50 * 1024 * 1024
MAX_EXPANDED_BYTES = 150 * 1024 * 1024
MAX_ARCHIVE_FILES = 2_000
USER_AGENT = "OSCLinux-Updater/1"
_VERSION_RE = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)
_ALLOWED_FILES = re.compile(
    r"^(?:OSCLinux\.py|osclinux_updater\.py|osclinux/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)$"
)


class UpdateError(RuntimeError):
    """A release could not be checked, verified, or staged safely."""


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    title: str
    notes: str
    asset_url: str
    sha256: str
    published_at: str | None


@dataclass(frozen=True)
class StagedUpdate:
    version: str
    directory: Path
    files: tuple[Path, ...]


def _version_key(value: str) -> tuple[int, int, int, int, tuple[tuple[int, Any], ...]]:
    match = _VERSION_RE.fullmatch(value.strip())
    if not match:
        raise UpdateError(f"Version invalide : {value!r}")
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    prerelease = match.group(4)
    # A final release sorts after every prerelease of the same numeric version.
    if prerelease is None:
        return major, minor, patch, 1, ()
    parts: list[tuple[int, Any]] = []
    for part in prerelease.split("."):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part.lower()))
    return major, minor, patch, 0, tuple(parts)


class ReleaseUpdater:
    """Read stable releases and stage a verified application ZIP from GitHub."""

    def __init__(
        self,
        current_version: str,
        *,
        repository: str = DEFAULT_REPOSITORY,
        cache_dir: Path | None = None,
        timeout: float = 12.0,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("repository doit avoir le format owner/name")
        _version_key(current_version)
        self.current_version = current_version.removeprefix("v")
        self.repository = repository
        self.timeout = timeout
        self.cache_dir = (cache_dir or Path.home() / ".cache" / "osclinux" / "updates").expanduser()

    @property
    def release_api_url(self) -> str:
        return f"https://api.github.com/repos/{self.repository}/releases/latest"

    def check(self) -> Release | None:
        """Return the newer stable release, or None when already current."""
        payload = self._get_json(self.release_api_url, max_bytes=1_000_000)
        if payload.get("draft") or payload.get("prerelease"):
            return None
        tag = payload.get("tag_name")
        if not isinstance(tag, str):
            raise UpdateError("La release GitHub ne contient pas de tag valide.")
        version = tag.removeprefix("v")
        if _version_key(version) <= _version_key(self.current_version):
            return None

        assets = payload.get("assets")
        if not isinstance(assets, list):
            raise UpdateError("La release ne contient pas de liste de fichiers valide.")
        candidates = [a for a in assets if isinstance(a, dict) and a.get("name") == "OSCLinux-update.zip"]
        if len(candidates) != 1:
            raise UpdateError("La release doit contenir exactement un fichier OSCLinux-update.zip.")
        asset = candidates[0]
        url = asset.get("browser_download_url")
        digest = asset.get("digest")
        if not isinstance(url, str) or not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise UpdateError("La release doit fournir une URL et un digest SHA-256 GitHub pour l'archive.")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
            raise UpdateError("L'URL de téléchargement de la release n'est pas autorisée.")
        sha256 = digest.partition(":")[2].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise UpdateError("Le digest SHA-256 de la release est invalide.")

        return Release(
            version=version,
            tag=tag,
            title=str(payload.get("name") or tag),
            notes=str(payload.get("body") or ""),
            asset_url=url,
            sha256=sha256,
            published_at=payload.get("published_at") if isinstance(payload.get("published_at"), str) else None,
        )

    def stage(self, release: Release) -> StagedUpdate:
        """Download, verify, and safely extract a release into a private cache."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.cache_dir / f"OSCLinux-{release.version}.zip"
        self._download(release.asset_url, archive_path)
        digest = _sha256_file(archive_path)
        if digest != release.sha256:
            archive_path.unlink(missing_ok=True)
            raise UpdateError("L'empreinte de l'archive ne correspond pas à celle publiée par GitHub.")

        stage_dir = Path(tempfile.mkdtemp(prefix=f"osclinux-{release.version}-", dir=self.cache_dir))
        try:
            files = _extract_application_zip(archive_path, stage_dir)
            if not files:
                raise UpdateError("L'archive ne contient aucun fichier de l'application.")
            return StagedUpdate(release.version, stage_dir, tuple(files))
        except Exception:
            shutil.rmtree(stage_dir, ignore_errors=True)
            raise
        finally:
            archive_path.unlink(missing_ok=True)

    def queue(self, release: Release) -> StagedUpdate:
        """Stage a release and persist it for application on the next launch."""
        staged = self.stage(release)
        marker = self.cache_dir / "pending-update.json"
        temporary_marker = self.cache_dir / "pending-update.json.tmp"
        payload = {
            "version": staged.version,
            "directory": str(staged.directory.resolve()),
            "files": [path.relative_to(staged.directory).as_posix() for path in staged.files],
        }
        try:
            descriptor = os.open(temporary_marker, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_marker, marker)
        except OSError as exc:
            temporary_marker.unlink(missing_ok=True)
            shutil.rmtree(staged.directory, ignore_errors=True)
            raise UpdateError(f"Impossible de préparer le redémarrage avec la mise à jour : {exc}") from exc
        return staged

    def apply_pending(self, *, install_dir: Path) -> bool:
        """Apply a queued update before application modules are imported.

        Returns True when an update was installed and the caller should restart
        the process immediately so Python loads the new code.
        """
        marker = self.cache_dir / "pending-update.json"
        if not marker.exists():
            return False
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            version = payload["version"]
            directory = Path(payload["directory"]).resolve()
            file_names = payload["files"]
            if not isinstance(version, str):
                raise ValueError("version invalide")
            _version_key(version)
            if directory.parent != self.cache_dir.resolve() or not directory.name.startswith(f"osclinux-{version}-"):
                raise ValueError("dossier temporaire hors cache ou invalide")
            if not isinstance(file_names, list) or not file_names:
                raise ValueError("liste de fichiers vide ou invalide")
            files: list[Path] = []
            for name in file_names:
                if not isinstance(name, str) or not _ALLOWED_FILES.fullmatch(name):
                    raise ValueError("chemin de fichier invalide")
                parts = PurePosixPath(name).parts
                candidate = directory.joinpath(*parts)
                parent = directory
                for component in parts[:-1]:
                    parent = parent / component
                    if parent.is_symlink():
                        raise ValueError("dossier temporaire contenant un lien symbolique")
                if candidate.is_symlink() or not candidate.is_file() or directory not in candidate.resolve().parents:
                    raise ValueError("fichier temporaire absent ou lien symbolique")
                files.append(candidate)
            staged = StagedUpdate(version, directory, tuple(files))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise UpdateError(f"La mise à jour préparée est invalide : {exc}") from exc

        apply_staged_update(staged, install_dir=install_dir)
        marker.unlink(missing_ok=True)
        shutil.rmtree(directory, ignore_errors=True)
        return True

    def _get_json(self, url: str, *, max_bytes: int) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT, "X-GitHub-Api-Version": "2022-11-28"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                _check_final_url(response.geturl(), allowed_hosts={"api.github.com"})
                data = response.read(max_bytes + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UpdateError(f"Impossible de consulter les mises à jour GitHub : {exc}") from exc
        if len(data) > max_bytes:
            raise UpdateError("La réponse GitHub dépasse la taille autorisée.")
        try:
            decoded = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError("GitHub a renvoyé une réponse JSON invalide.") from exc
        if not isinstance(decoded, dict):
            raise UpdateError("La réponse GitHub n'a pas le format attendu.")
        return decoded

    def _download(self, url: str, destination: Path) -> None:
        _check_final_url(url, allowed_hosts={"github.com", "www.github.com"})
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"})
        temp_path = destination.with_suffix(destination.suffix + ".part")
        total = 0
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response, temp_path.open("wb") as output:
                _check_final_url(
                    response.geturl(),
                    allowed_hosts={"github.com", "www.github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"},
                )
                while chunk := response.read(64 * 1024):
                    total += len(chunk)
                    if total > MAX_RELEASE_BYTES:
                        raise UpdateError("L'archive dépasse la taille maximale autorisée (50 Mio).")
                    output.write(chunk)
            if total == 0:
                raise UpdateError("GitHub a renvoyé une archive vide.")
            os.replace(temp_path, destination)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            temp_path.unlink(missing_ok=True)
            raise UpdateError(f"Impossible de télécharger la mise à jour : {exc}") from exc
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise


def _check_final_url(url: str, *, allowed_hosts: set[str]) -> None:
    parsed = urllib.parse.urlparse(url)
    try:
        valid_port = parsed.port in (None, 443)
    except ValueError:
        valid_port = False
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or not valid_port
    ):
        raise UpdateError("Redirection vers une adresse non autorisée refusée.")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_application_zip(archive_path: Path, destination: Path) -> list[Path]:
    extracted: list[Path] = []
    total_size = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_FILES:
                raise UpdateError("L'archive contient trop de fichiers.")
            for info in infos:
                if info.is_dir():
                    continue
                raw_name = info.filename
                posix = PurePosixPath(raw_name)
                if posix.is_absolute() or ".." in posix.parts or "\\" in raw_name or not _ALLOWED_FILES.fullmatch(raw_name):
                    raise UpdateError(f"Chemin interdit dans l'archive : {raw_name!r}")
                # ZIP external attributes encode Unix file type. Reject links and special files.
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                file_type = unix_mode & 0o170000
                if file_type not in (0, 0o100000):
                    raise UpdateError(f"Type de fichier interdit dans l'archive : {raw_name!r}")
                total_size += info.file_size
                if total_size > MAX_EXPANDED_BYTES:
                    raise UpdateError("L'archive décompressée dépasse la taille maximale autorisée.")
                target = destination.joinpath(*posix.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(info) as source, target.open("xb") as output:
                    while chunk := source.read(64 * 1024):
                        written += len(chunk)
                        if written > info.file_size or total_size - info.file_size + written > MAX_EXPANDED_BYTES:
                            raise UpdateError("La taille réelle décompressée dépasse la limite autorisée.")
                        output.write(chunk)
                if written != info.file_size:
                    raise UpdateError(f"Taille incohérente pour {raw_name!r}.")
                extracted.append(target)
    except zipfile.BadZipFile as exc:
        raise UpdateError("Le fichier téléchargé n'est pas une archive ZIP valide.") from exc
    return extracted


def apply_staged_update(staged: StagedUpdate, *, install_dir: Path, backup_dir: Path | None = None) -> None:
    """Apply a staged release transactionally; call only while the app is stopped.

    Only OSCLinux.py, osclinux_updater.py, and osclinux/ are replaceable. User
    configuration, modules, and unrelated files are left alone. Existing files
    are backed up and restored if any replacement fails.
    """
    root = install_dir.resolve()
    backup_root = (backup_dir or staged.directory.parent / f"backup-{staged.version}").resolve()
    if not root.is_dir():
        raise UpdateError("Le dossier d'installation n'existe pas.")
    if backup_root == root or root in backup_root.parents:
        raise UpdateError("Le dossier de sauvegarde ne peut pas être dans le dossier d'installation.")

    changed: list[tuple[Path, Path | None]] = []
    try:
        for source in staged.files:
            relative = source.relative_to(staged.directory)
            if not _ALLOWED_FILES.fullmatch(relative.as_posix()):
                raise UpdateError(f"Chemin interdit lors de l'installation : {relative}")
            target = root.joinpath(*relative.parts)
            if root not in target.resolve().parents and target.resolve() != root:
                raise UpdateError(f"Le fichier cible sort du dossier d'installation : {relative}")
            if target.exists() and target.is_symlink():
                raise UpdateError(f"Le fichier cible est un lien symbolique : {relative}")
            backup = backup_root.joinpath(*relative.parts) if target.exists() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            if backup is not None:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            changed.append((target, backup))
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".osclinux-new", dir=target.parent)
            os.close(fd)
            temp_target = Path(temp_name)
            shutil.copy2(source, temp_target)
            os.replace(temp_target, target)
    except Exception as exc:
        for target, backup in reversed(changed):
            try:
                if backup is None:
                    target.unlink(missing_ok=True)
                elif backup.exists():
                    os.replace(backup, target)
            except OSError:
                pass
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"Échec de l'installation ; restauration tentée : {exc}") from exc
