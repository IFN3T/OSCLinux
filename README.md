# OSCLinux

OSCLinux currently provides its Qt main window and the GitHub Releases updater.
Spotify and VRChat OSC integrations will be added as optional modules.

Use Python 3.10 or newer and a project-local virtual environment for all
dependencies and commands:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python OSCLinux.py
```

The app checks for updates at startup without blocking the Qt interface. It
offers a newer version and applies an accepted update at the next launch. The
command `python3 OSCLinux.py --check-updates` checks the release channel and
exits, which is useful for diagnostics.

## Main program updates

`osclinux_updater.py` checks the GitHub stable Releases channel for
`IFN3T/OSCLinux`. A newer release is offered to the user; the updater does not
install anything just because a release exists. After confirmation, `queue()`
downloads and stages the update for the next launch. The application applies it
before importing the rest of its modules, then restarts to load the new code.

Network checks use HTTPS and a bounded timeout. Downloads are limited to 50 MiB,
verified against GitHub's SHA-256 release asset digest, and extracted only to
`OSCLinux.py`, `osclinux_updater.py`, and `osclinux/`. Archive traversal, symlinks, oversized archives,
and redirects outside the GitHub release asset hosts are rejected. Installation
backs up replaced files and attempts rollback on failure. Modules and user data
are never overwritten by this updater.

The updater uses only the Python standard library; the main window uses PySide6.
A network or GitHub error does not prevent the current version from starting.

Run the updater regression checks inside the same virtual environment with:

```sh
source .venv/bin/activate
python -m unittest discover -s tests -v
```

## Publishing a program update

1. Update `APP_VERSION` in `OSCLinux.py` and commit the release source.
2. Create a GitHub Release whose tag is a semantic version such as `v0.2.0`.
3. Attach exactly one asset named `OSCLinux-update.zip`.
4. Put `OSCLinux.py`, `osclinux_updater.py`, and any `osclinux/` package files
   at the root of the ZIP. Do not include settings, modules, credentials, or
   user data.
5. Publish the release. GitHub must expose a SHA-256 digest for the asset; the
   updater refuses to stage the release if that digest is unavailable.

Only stable releases are considered. Pre-releases and invalid version tags are
ignored or rejected. The repository owner and GitHub account remain the trust
root for releases; for stronger protection against account compromise, release
signing can be added when the signing key is provisioned.
