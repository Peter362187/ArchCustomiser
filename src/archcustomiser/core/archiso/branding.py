"""Branding: os-release, Startbildschirm, Hintergrundbild, Begruessungstext.

Zur Herkunftsangabe: ``/etc/os-release`` bekommt ``ID_LIKE=arch`` und ein
``PRETTY_NAME`` mit dem Zusatz „based on Arch Linux". Das ist der in
``os-release(5)`` vorgesehene, maschinenlesbare Herkunftsnachweis -- das System
gibt damit keine falsche Auskunft ueber seine Grundlage. ``ID_LIKE`` wird
erzwungen, auch wenn jemand die Felder anderweitig ueberschreibt.

``IMAGE_ID`` und ``IMAGE_VERSION`` werden bewusst **nicht** gesetzt: mkarchiso
loescht beide per ``sed`` und schreibt sie selbst aus ``iso_name`` und
``iso_version``. Doppelte Pflege waere nur eine Fehlerquelle.
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path

from ..config import BuildConfig
from ..validation import MAX_MENU_TITLE_LENGTH, MENU_TITLE_FORBIDDEN
from .errors import MissingAssetError
from .quoting import shell_quote
from .settings import ArchisoSettings
from .tree import ProfileTree

log = logging.getLogger(__name__)

ORIGIN = "branding"
AIROOTFS = "airootfs"

MAX_ASSET_BYTES = 16 * 1024 * 1024
SPLASH_SIZE = (640, 480)

WALLPAPER_TARGET = "usr/share/backgrounds/archcustomiser/wallpaper"
LOGO_TARGET = "usr/share/pixmaps"


def build_branding(
    tree: ProfileTree, config: BuildConfig, settings: ArchisoSettings
) -> None:
    _os_release(tree, config)
    _motd(tree, config)
    _splash(tree, config)
    _wallpaper(tree, config)
    _logo(tree, config)


def menu_title(config: BuildConfig) -> str:
    """Der Titel fuer alle Bootmenues -- auf unbedenkliche Zeichen beschraenkt.

    Der Wert geht in drei Formate mit drei Syntaxen: syslinux und systemd-boot
    sind zeilenbasiert, GRUB wertet seine Konfiguration als Skript aus. Ein
    Anfuehrungszeichen im Titel schliesst dort die Zeichenkette mitten im
    ``menuentry`` und laesst den Rest der Zeile als Befehle zurueck.

    Die Oberflaeche prueft das bereits ueber den Validator ``menu_title``. Diese
    zweite Linie greift, wenn ein Profil an ihr vorbeikommt -- eine geladene
    YAML-Datei etwa, die von einem anderen Rechner stammt. Dort wird nicht
    abgelehnt, sondern bereinigt: ein Profil soll an einem Anzeigetext nicht
    scheitern.
    """
    explicit = config.field_str("branding.boot_menu_title")
    roh = explicit or f"{config.distro_name} {config.version}"
    sicher = _clean_menu_title(roh)
    if sicher != roh:
        log.warning(
            "Bootmenue-Titel enthielt Zeichen, die die Menuedatei zerlegt haetten, "
            "und wurde bereinigt: %r -> %r",
            roh,
            sicher,
        )
    return sicher or "Linux"


def _clean_menu_title(value: str) -> str:
    ohne_sonderzeichen = "".join(
        zeichen
        for zeichen in value
        if zeichen not in MENU_TITLE_FORBIDDEN
        and zeichen >= " "
        and zeichen != chr(127)
    )
    return " ".join(ohne_sonderzeichen.split())[:MAX_MENU_TITLE_LENGTH]


# ---------------------------------------------------------------------------
# Textdateien
# ---------------------------------------------------------------------------


def _os_release(tree: ProfileTree, config: BuildConfig) -> None:
    name = config.distro_name
    identifier = config.iso_name          # bereits kleingeschrieben und bereinigt

    fields: list[tuple[str, str]] = [
        ("NAME", _os_release_value(name, "NAME")),
        (
            "PRETTY_NAME",
            _os_release_value(f"{name} {config.version} (based on Arch Linux)", "PRETTY_NAME"),
        ),
        ("ID", _os_release_value(identifier, "ID")),
        # Der maschinenlesbare Herkunftsnachweis. Nicht verhandelbar.
        ("ID_LIKE", "arch"),
        ("BUILD_ID", "rolling"),
        ("VERSION_ID", _os_release_value(config.version, "VERSION_ID")),
        ("ANSI_COLOR", '"38;2;23;147;209"'),
    ]

    home = config.field_str("branding.home_url")
    if home:
        fields.append(("HOME_URL", _os_release_value(home, "HOME_URL")))
    bug = config.field_str("branding.bug_url")
    if bug:
        fields.append(("BUG_REPORT_URL", _os_release_value(bug, "BUG_REPORT_URL")))
    # Auf die Arch-Dokumentation zu verweisen ist korrekte Quellenangabe und
    # keine Behauptung einer Zugehoerigkeit.
    fields.append(("DOCUMENTATION_URL", '"https://wiki.archlinux.org/"'))

    if config.field_str("branding.logo"):
        fields.append(("LOGO", _os_release_value(f"{identifier}-logo", "LOGO")))

    body = "\n".join(f"{key}={value}" for key, value in fields)
    tree.add_file(
        f"{AIROOTFS}/etc/os-release",
        "# Erzeugt von ArchCustomiser.\n"
        "# IMAGE_ID und IMAGE_VERSION fehlen absichtlich -- mkarchiso setzt sie.\n"
        + body
        + "\n",
        origin=ORIGIN,
    )


def _os_release_value(value: str, field: str) -> str:
    """Ein os-release-Wert, sicher als Shell-Literal.

    ``/etc/os-release`` ist kein Datenformat, sondern ein Shell-Fragment: die
    uebliche Art es zu lesen ist ``. /etc/os-release`` -- dieses Projekt tut das
    in ``core/build/wsl.py`` selbst. Ein Wert in doppelten Anfuehrungszeichen
    wird dabei weiter ersetzt, ``NAME="Test$(whoami)"`` fuehrt also whoami aus.

    Die frueher hier verwendete Maskierung fing Backslash und Anfuehrungszeichen
    ab, aber weder ``$`` noch Backtick -- und war damit wirkungslos gegen genau
    den Angriff, gegen den ``profiledef.sh`` seit jeher geschuetzt ist. Deshalb
    jetzt dieselbe Grenze wie dort: einfache Anfuehrungszeichen ueber
    ``shlex.quote``, die in Bash jede Ersetzung unterbinden.

    ``os-release(5)`` erlaubt beide Anfuehrungszeichenarten ausdruecklich, und
    systemds eigener Parser liest einfache genauso wie doppelte.
    """
    return shell_quote(value, field=field)
def _motd(tree: ProfileTree, config: BuildConfig) -> None:
    name = config.distro_name
    lines = [
        f"Willkommen bei {name} {config.version}",
        "",
        "Dieses System basiert auf Arch Linux.",
    ]
    if config.field_bool("build.include_installer", True):
        lines += [
            "",
            "Zum dauerhaften Installieren auf die Festplatte:",
            "    archinstall --config /etc/archcustomiser/archinstall.json",
            "",
            "Ohne Installation bleibt dieses System nur bis zum Neustart bestehen.",
        ]
    home = config.field_str("branding.home_url")
    if home:
        lines += ["", home]
    tree.add_file(f"{AIROOTFS}/etc/motd", "\n".join(lines) + "\n", origin=ORIGIN)


# ---------------------------------------------------------------------------
# Bilddateien
# ---------------------------------------------------------------------------


def _read_asset(raw_path: str, *, label: str) -> bytes:
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise MissingAssetError(str(path), f"{label}: Datei nicht gefunden")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise MissingAssetError(str(path), f"{label}: nicht lesbar ({exc})") from exc
    if size == 0:
        raise MissingAssetError(str(path), f"{label}: Datei ist leer")
    if size > MAX_ASSET_BYTES:
        raise MissingAssetError(
            str(path), f"{label}: groesser als {MAX_ASSET_BYTES // 1048576} MB"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise MissingAssetError(str(path), f"{label}: nicht lesbar ({exc})") from exc


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Breite und Hoehe aus dem PNG-Kopf -- ohne Fremdbibliothek.

    Der IHDR-Block steht bei einem gueltigen PNG immer an derselben Stelle.
    """
    if len(data) < 26 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if data[12:16] != b"IHDR":
        return None
    try:
        width, height = struct.unpack(">II", data[16:24])
    except struct.error:
        return None
    return width, height


def _splash(tree: ProfileTree, config: BuildConfig) -> None:
    """Hintergrund des BIOS-Bootmenues.

    mkarchiso kopiert diese Datei nur, wenn sie exakt ``splash.png`` heisst --
    andere Dateinamen im Verzeichnis ``syslinux/`` werden ignoriert.
    """
    raw = config.field_str("branding.splash")
    if not raw:
        return
    try:
        data = _read_asset(raw, label="Startbild")
    except MissingAssetError as exc:
        tree.note(exc.user_message)
        return

    size = png_dimensions(data)
    if size is None:
        tree.note(
            f"{raw} ist keine gueltige PNG-Datei. Das BIOS-Bootmenue kann nur PNG "
            f"anzeigen; das Bild wird nicht verwendet."
        )
        return
    if size != SPLASH_SIZE:
        # Kein Abbruch: syslinux skaliert nicht, zeigt das Bild aber trotzdem.
        tree.note(
            f"Das Startbild ist {size[0]}x{size[1]} Pixel gross. Das BIOS-Bootmenue "
            f"erwartet {SPLASH_SIZE[0]}x{SPLASH_SIZE[1]}; andere Groessen werden "
            f"nicht skaliert und koennen abgeschnitten erscheinen."
        )

    tree.add_file("syslinux/splash.png", data, origin=ORIGIN)


def _wallpaper(tree: ProfileTree, config: BuildConfig) -> None:
    """Desktop-Hintergrund.

    Landet zusaetzlich in ``/etc/skel``, weil mkarchiso dessen Inhalt in die
    Home-Verzeichnisse kopiert.
    """
    raw = config.field_str("branding.wallpaper")
    if not raw:
        return
    try:
        data = _read_asset(raw, label="Hintergrundbild")
    except MissingAssetError as exc:
        tree.note(exc.user_message)
        return

    suffix = Path(raw).suffix.lower() or ".png"
    target = f"{WALLPAPER_TARGET}{suffix}"
    tree.add_file(f"{AIROOTFS}/{target}", data, origin=ORIGIN)

    # Der Hinweis ist wichtig, damit niemand mehr erwartet als geliefert wird.
    tree.note(
        "Das Hintergrundbild gilt fuer die Live-Sitzung. Ein spaeter mit "
        "archinstall installiertes System bekommt sein /etc/skel frisch aus den "
        "Paketen und uebernimmt es nicht automatisch."
    )


def _logo(tree: ProfileTree, config: BuildConfig) -> None:
    """Systemlogo -- wird unter anderem von fastfetch ueber os-release gefunden."""
    raw = config.field_str("branding.logo")
    if not raw:
        return
    try:
        data = _read_asset(raw, label="Logo")
    except MissingAssetError as exc:
        tree.note(exc.user_message)
        return

    suffix = Path(raw).suffix.lower() or ".png"
    tree.add_file(
        f"{AIROOTFS}/{LOGO_TARGET}/{config.iso_name}-logo{suffix}",
        data,
        origin=ORIGIN,
    )
