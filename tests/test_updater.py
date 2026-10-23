from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from osclinux_updater import (
    Release,
    ReleaseUpdater,
    UpdateError,
    _extract_application_zip,
    _version_key,
)


class VersionTests(unittest.TestCase):
    def test_semantic_version_order(self) -> None:
        self.assertLess(_version_key("0.9.9"), _version_key("0.10.0"))
        self.assertLess(_version_key("1.2.0-rc.2"), _version_key("1.2.0-rc.10"))
        self.assertLess(_version_key("1.2.0-rc.10"), _version_key("1.2.0"))

    def test_rejects_invalid_version(self) -> None:
        with self.assertRaises(UpdateError):
            _version_key("latest")


class ReleaseCheckTests(unittest.TestCase):
    def test_no_release_yet_is_a_normal_state(self) -> None:
        updater = ReleaseUpdater("0.1.0")
        error = urllib.error.HTTPError(updater.release_api_url, 404, "Not Found", {}, io.BytesIO(b""))
        with patch("osclinux_updater.urllib.request.urlopen", side_effect=error):
            self.assertIsNone(updater.check())

    def test_detects_newer_release_and_requires_github_digest(self) -> None:
        updater = ReleaseUpdater("0.1.0")
        payload = {
            "tag_name": "v0.2.0",
            "name": "OSCLinux 0.2.0",
            "body": "Update notes",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": "OSCLinux-update.zip",
                    "browser_download_url": "https://github.com/IFN3T/OSCLinux/releases/download/v0.2.0/OSCLinux-update.zip",
                    "digest": "sha256:" + "a" * 64,
                }
            ],
        }
        with patch.object(updater, "_get_json", return_value=payload):
            release = updater.check()
        self.assertIsNotNone(release)
        self.assertEqual(release.version, "0.2.0")
        self.assertEqual(release.sha256, "a" * 64)

        payload["assets"][0].pop("digest")
        with patch.object(updater, "_get_json", return_value=payload):
            with self.assertRaises(UpdateError):
                updater.check()


class StagingTests(unittest.TestCase):
    def _release_and_archive(self) -> tuple[Release, bytes]:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("OSCLinux.py", "APP_VERSION = '0.2.0'\n")
            archive.writestr("osclinux_updater.py", "# updated updater\n")
        data = buffer.getvalue()
        release = Release(
            version="0.2.0",
            tag="v0.2.0",
            title="OSCLinux 0.2.0",
            notes="",
            asset_url="https://github.com/IFN3T/OSCLinux/releases/download/v0.2.0/OSCLinux-update.zip",
            sha256=hashlib.sha256(data).hexdigest(),
            published_at=None,
        )
        return release, data

    def test_queue_and_apply_pending_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            install = root / "app"
            install.mkdir()
            (install / "OSCLinux.py").write_text("APP_VERSION = '0.1.0'\n", encoding="utf-8")
            (install / "settings.json").write_text("{}", encoding="utf-8")
            updater = ReleaseUpdater("0.1.0", cache_dir=cache)
            release, archive = self._release_and_archive()

            def fake_download(_url: str, destination: Path) -> None:
                destination.write_bytes(archive)

            with patch.object(updater, "_download", side_effect=fake_download):
                updater.queue(release)

            next_launch = ReleaseUpdater("0.1.0", cache_dir=cache)
            self.assertTrue(next_launch.apply_pending(install_dir=install))
            self.assertIn("0.2.0", (install / "OSCLinux.py").read_text(encoding="utf-8"))
            self.assertEqual((install / "settings.json").read_text(encoding="utf-8"), "{}")
            self.assertFalse((cache / "pending-update.json").exists())

    def test_rejects_zip_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "malicious.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../OSCLinux.py", "malicious")
            with self.assertRaises(UpdateError):
                _extract_application_zip(archive_path, root / "stage")


if __name__ == "__main__":
    unittest.main()
