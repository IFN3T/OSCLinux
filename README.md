# OSCLinux

OSCLinux is in its initial setup. The repository currently contains the main
program updater, ready to be called by the Qt startup flow once the application
interface is added.

## Main program updates

`osclinux_updater.py` checks the GitHub stable Releases channel for
`IFN3T/OSCLinux`. A newer release is offered to the user; the updater does not
install anything just because a release exists. After confirmation, the caller
downloads and stages the update. The application should apply the staged files
after it has exited, before importing the updated modules on the next launch.

```python
from pathlib import Path

from osclinux_updater import ReleaseUpdater, UpdateError, apply_staged_update

APP_VERSION = "0.1.0"
updater = ReleaseUpdater(APP_VERSION)

try:
    release = updater.check()
    if release is not None:
        # Present release.title, release.version and release.notes to the user.
        # Only call stage() after the user chooses to download the update.
        staged = updater.stage(release)
        # Persist staged.directory and staged.version for the next launch.
        # On next launch, after the previous process has stopped:
        # apply_staged_update(staged, install_dir=Path(__file__).parent)
except UpdateError as exc:
    # Log the error and continue starting the current version offline.
    print(f"Mise à jour indisponible : {exc}")
```

Network checks use HTTPS and a bounded timeout. Downloads are limited to 50 MiB,
verified against GitHub's SHA-256 release asset digest, and extracted only to
`OSCLinux.py` and `osclinux/`. Archive traversal, symlinks, oversized archives,
and redirects outside the GitHub release asset hosts are rejected. Installation
backs up replaced files and attempts rollback on failure. Modules and user data
are never overwritten by this updater.

The updater uses only the Python standard library. Release checks should run in
a worker thread so the Qt interface stays responsive. A network or GitHub error
must not prevent the current version from starting.

## Publishing a program update

1. Update the application's `APP_VERSION` and commit the release source.
2. Create a GitHub Release whose tag is a semantic version such as `v0.2.0`.
3. Attach exactly one asset named `OSCLinux-update.zip`.
4. Put `OSCLinux.py` and any `osclinux/` package files at the root of the ZIP.
   Do not include settings, modules, credentials, or user data.
5. Publish the release. GitHub must expose a SHA-256 digest for the asset; the
   updater refuses to stage the release if that digest is unavailable.

Only stable releases are considered. Pre-releases and invalid version tags are
ignored or rejected. The repository owner and GitHub account remain the trust
root for releases; for stronger protection against account compromise, release
signing can be added when the signing key is provisioned.
