"""Ein nachgebildetes ``mkarchiso`` fuer die Tests.

Gibt aufgezeichnete Ausgabe im echten Format aus -- einschliesslich der
Fortschrittszeilen von pacman, mksquashfs und xorriso, die mit Wagenruecklauf
statt Zeilenumbruch enden. Genau daran scheitert ein naiv gebauter Leser.

Wird als eigenstaendiges Programm gestartet, damit der Test den echten
Prozesspfad durchlaeuft: ``Popen``, Puffer, Signale, Abbruch. Ein Mock des
Subprozesses wuerde genau die Stellen ueberspringen, an denen Fehler stecken.

Aufruf wie mkarchiso::

    fake_mkarchiso.py -v -w WORK -o OUT PROFILE

Umgebungsvariablen steuern das Verhalten:

* ``FAKE_FAIL_AT``   -- nach dieser Marke mit Fehler abbrechen
* ``FAKE_SLOW``      -- Sekunden Pause je Zeile (fuer den Abbruchtest)
* ``FAKE_NO_ISO``    -- Erfolg melden, aber keine ISO anlegen
* ``FAKE_ISO_NAME``  -- Name der erzeugten Datei
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

APP = "mkarchiso"


def info(text: str) -> None:
    sys.stdout.write(f"[{APP}] INFO: {text}\n")
    sys.stdout.flush()


def error(text: str) -> None:
    sys.stdout.write(f"[{APP}] ERROR: {text}\n")
    sys.stdout.flush()


def warning(text: str) -> None:
    sys.stdout.write(f"[{APP}] WARNING: {text}\n")
    sys.stdout.flush()


def raw(text: str) -> None:
    """Ausgabe eines aufgerufenen Werkzeugs -- ohne mkarchiso-Praefix."""
    sys.stdout.write(text)
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    out_dir = Path(".")
    slow = float(os.environ.get("FAKE_SLOW", "0"))
    fail_at = os.environ.get("FAKE_FAIL_AT", "")

    for index, item in enumerate(argv):
        if item == "-o" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])

    def step(marker: str) -> bool:
        """Gibt eine Marke aus. False, wenn hier abgebrochen werden soll."""
        if slow:
            time.sleep(slow)
        info(marker)
        return fail_at not in marker or not fail_at

    if not step("Validating options..."):
        error("Validating 'bios.syslinux': The 'syslinux' package is missing from the package list!")
        error("1 errors were encountered while validating the profile. Aborting.")
        return 1

    info("mkarchiso configuration settings")
    info("             Architecture:   x86_64")
    info("        Working directory:   /work")

    for marker in ("Copying custom pacman.conf to work directory...",):
        if not step(marker):
            error("Failed to copy pacman.conf")
            return 1
        info("Done!")

    if not step("Copying custom airootfs files..."):
        error("Cannot copy airootfs")
        return 1
    warning("Cannot change permissions of '/work/x86_64/airootfs/etc/gibtesnicht'. The file or directory does not exist.")
    info("Done!")

    # -- pacstrap, mit den echten pacman-Zaehlern ---------------------------
    if not step("Installing packages to '/work/x86_64/airootfs/'..."):
        error("failed to install packages to new root")
        return 1
    total = 40
    raw(f"Packages ({total}) base-1-2  linux-6.9-1  firefox-154.0.1-1\n")
    raw(":: Retrieving packages...\n")
    for number in range(1, total + 1):
        if slow:
            time.sleep(slow / 10)
        raw(f" ({number:>3}/{total}) downloading paket-{number}.pkg.tar.zst\n")
    raw(":: Processing package changes...\n")
    for number in range(1, total + 1):
        if slow:
            time.sleep(slow / 10)
        raw(f" ({number:>3}/{total}) installing paket-{number}\n")
    info("Done! Packages installed successfully.")

    for marker in (
        "Creating version files...",
        "Copying /etc/skel/* to user homes...",
        "Copying /boot out of the airootfs...",
        # Der Tippfehler steht so im Original.
        "Creating a list of installed packages on live-enviroment...",
        "Preparing kernel and initramfs for the ISO 9660 file system...",
        "Setting up SYSLINUX for BIOS booting...",
        "Preparing kernel and initramfs for the FAT file system...",
        "Creating FAT image of size: 128 MiB...",
        "Setting up systemd-boot for UEFI booting...",
        "Cleaning up in pacstrap location...",
    ):
        if not step(marker):
            error(f"Failed during: {marker}")
            return 1
        info("Done!")

    # -- mksquashfs: Fortschritt mit Wagenruecklauf --------------------------
    if not step("Creating SquashFS image, this may take some time..."):
        error("mksquashfs failed")
        return 1
    for percent in (12, 43, 76, 100):
        if slow:
            time.sleep(slow / 4)
        raw(f"[=====|    ] {percent * 98}/9800  {percent}%\r")
    raw("\n")
    info("Done!")

    if not step("Creating checksum file for self-test..."):
        error("sha512sum failed")
        return 1
    info("Done!")

    # -- xorriso -------------------------------------------------------------
    if not step("Creating ISO image..."):
        error("xorriso failed")
        return 1
    for percent in ("12.30", "55.20", "99.10"):
        if slow:
            time.sleep(slow / 4)
        raw(f"xorriso : UPDATE :  {percent}% done\r")
    raw("\n")

    if not os.environ.get("FAKE_NO_ISO"):
        out_dir.mkdir(parents=True, exist_ok=True)
        name = os.environ.get("FAKE_ISO_NAME", "flos-1.0-x86_64.iso")
        (out_dir / name).write_bytes(b"ISO9660" + b"\0" * 4096)
    info("Done!")
    info("Done! | 4.2 MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
