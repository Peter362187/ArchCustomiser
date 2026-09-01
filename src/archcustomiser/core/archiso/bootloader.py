"""Bootloader-Konfiguration: ``syslinux/``, ``efiboot/`` und ``grub/``.

Die Platzhalter ``%INSTALL_DIR%``, ``%ARCH%`` und ``%ARCHISO_UUID%`` bleiben
woertlich stehen -- mkarchiso ersetzt sie beim Bauen. Sie hier vorab einzusetzen
waere falsch: ``%ARCHISO_UUID%`` kennt nur mkarchiso, es ist der Zeitstempel des
Bauvorgangs.

Wo *nicht* ersetzt wird, ist ebenso wichtig: in ``efiboot/loader/loader.conf``
findet **keine** Ersetzung statt (mkarchiso kopiert die Datei mit ``install``,
ohne ``sed``). Ein Platzhalter darin bliebe woertlich stehen und wuerde den
Bootloader verwirren. ``%ARCHISO_SEARCH_FILENAME%`` wiederum gibt es nur in
GRUB-Dateien.

Ein zweiter Fallstrick betrifft die optionalen Menueeintraege: GRUB kann per
``-f`` selbst pruefen, ob eine Datei vorhanden ist, und blendet den Eintrag
sonst aus. syslinux und systemd-boot koennen das nicht -- dort wird der Eintrag
nur geschrieben, wenn das zugehoerige Paket auch installiert wird.
"""

from __future__ import annotations

from .settings import ArchisoSettings
from .tree import ProfileTree

ORIGIN = "generator"

# Pfade der Speichertest-Abbilder auf der ISO. Absolut ab ISO-Wurzel, also
# bewusst ohne %INSTALL_DIR% -- mkarchiso legt sie dorthin.
MEMTEST_BIOS = "/boot/memtest86+/memtest"
MEMTEST_EFI = "/boot/memtest86+/memtest.efi"


def build_bootloaders(tree: ProfileTree, settings: ArchisoSettings, menu_title: str) -> None:
    if settings.has_bios:
        _syslinux(tree, settings, menu_title)
    if settings.has_systemd_boot:
        _systemd_boot(tree, settings, menu_title)
    if settings.has_grub:
        _grub(tree, settings, menu_title)


# ---------------------------------------------------------------------------
# BIOS: syslinux
# ---------------------------------------------------------------------------


def _syslinux(tree: ProfileTree, settings: ArchisoSettings, menu_title: str) -> None:
    """Eine Menuedatei plus eine Eintragsdatei.

    Die Aufteilung von archiso/releng auf sechs Dateien dient dort dem
    PXE-Netzwerkstart, den dieses Programm nicht anbietet. Zwei Dateien sind
    uebersichtlicher und erfuellen dieselbe Aufgabe.

    ``vesamenu.c32`` statt ``menu.c32``, weil nur die Grafikvariante ein
    Hintergrundbild anzeigen kann.
    """
    head = f"""# Erzeugt von ArchCustomiser -- nicht von Hand bearbeiten.
SERIAL 0 115200
UI vesamenu.c32
MENU TITLE {menu_title}
MENU BACKGROUND splash.png

MENU WIDTH 78
MENU MARGIN 4
MENU ROWS 6
MENU VSHIFT 10
MENU TABMSGROW 13
MENU CMDLINEROW 13
MENU HELPMSGROW 15
MENU HELPMSGENDROW 29

MENU COLOR border       30;44   #40ffffff #a0000000 std
MENU COLOR title        1;36;44 #9033ccff #a0000000 std
MENU COLOR sel          7;37;40 #e0ffffff #20ffffff all
MENU COLOR unsel        37;44   #50ffffff #a0000000 std
MENU COLOR help         37;40   #c0ffffff #a0000000 std
MENU COLOR timeout_msg  37;40   #80ffffff #00000000 std
MENU COLOR timeout      1;37;40 #c0ffffff #00000000 std
MENU COLOR msg07        37;40   #90ffffff #a0000000 std
MENU COLOR tabmsg       31;40   #30ffffff #00000000 std

MENU CLEAR
MENU IMMEDIATE

DEFAULT arch
TIMEOUT {settings.boot_timeout * 10}

INCLUDE syslinux-linux.cfg
"""
    # syslinux rechnet die Wartezeit in Zehntelsekunden.
    tree.add_file("syslinux/syslinux.cfg", head, origin=ORIGIN)

    entries = f"""# Erzeugt von ArchCustomiser -- nicht von Hand bearbeiten.
LABEL arch
TEXT HELP
{menu_title} vom Medium starten (BIOS).
ENDTEXT
MENU LABEL {menu_title} (%ARCH%, BIOS)
LINUX /%INSTALL_DIR%/boot/%ARCH%/{settings.vmlinuz}
INITRD /%INSTALL_DIR%/boot/%ARCH%/{settings.initramfs}
APPEND {settings.boot_options()}

LABEL archspeech
TEXT HELP
{menu_title} mit Bildschirmvorlesen starten (BIOS).
ENDTEXT
MENU LABEL {menu_title} (%ARCH%, BIOS) mit ^Sprachausgabe
LINUX /%INSTALL_DIR%/boot/%ARCH%/{settings.vmlinuz}
INITRD /%INSTALL_DIR%/boot/%ARCH%/{settings.initramfs}
APPEND {settings.boot_options()} accessibility=on
"""
    if settings.include_memtest:
        entries += f"""
LABEL memtest
MENU LABEL Arbeitsspeicher pruefen (Memtest86+)
LINUX {MEMTEST_BIOS}
"""
    entries += """
LABEL reboot
MENU LABEL Neu starten
COM32 reboot.c32

LABEL poweroff
MENU LABEL Ausschalten
COM32 poweroff.c32
"""
    tree.add_file("syslinux/syslinux-linux.cfg", entries, origin=ORIGIN)


# ---------------------------------------------------------------------------
# UEFI: systemd-boot
# ---------------------------------------------------------------------------


def _systemd_boot(tree: ProfileTree, settings: ArchisoSettings, menu_title: str) -> None:
    default_entry = "01-archcustomiser-linux.conf"

    # ACHTUNG: In dieser Datei ersetzt mkarchiso KEINE Platzhalter. Sie wird mit
    # 'install' kopiert, nicht durch sed geschickt.
    tree.add_file(
        "efiboot/loader/loader.conf",
        "# Erzeugt von ArchCustomiser.\n"
        "# Achtung: mkarchiso kopiert diese Datei unveraendert und ersetzt darin\n"
        "# keine Vorlagenmarken. Sie muss deshalb fertige Werte enthalten.\n"
        f"timeout {settings.boot_timeout}\n"
        f"default {default_entry}\n"
        "beep on\n",
        origin=ORIGIN,
    )

    tree.add_file(
        f"efiboot/loader/entries/{default_entry}",
        f"title    {menu_title} (%ARCH%, UEFI)\n"
        f"sort-key 01\n"
        f"linux    /%INSTALL_DIR%/boot/%ARCH%/{settings.vmlinuz}\n"
        f"initrd   /%INSTALL_DIR%/boot/%ARCH%/{settings.initramfs}\n"
        f"options  {settings.boot_options()}\n",
        origin=ORIGIN,
    )

    tree.add_file(
        "efiboot/loader/entries/02-archcustomiser-speech-linux.conf",
        f"title    {menu_title} (%ARCH%, UEFI) mit Sprachausgabe\n"
        f"sort-key 02\n"
        f"linux    /%INSTALL_DIR%/boot/%ARCH%/{settings.vmlinuz}\n"
        f"initrd   /%INSTALL_DIR%/boot/%ARCH%/{settings.initramfs}\n"
        f"options  {settings.boot_options()} accessibility=on\n",
        origin=ORIGIN,
    )

    if settings.include_memtest:
        # 'architecture' ist kein systemd-boot-Schluessel, sondern ein Filter
        # von mkarchiso: Eintraege fremder UEFI-Architekturen werden verworfen.
        tree.add_file(
            "efiboot/loader/entries/03-memtest86+.conf",
            "title    Arbeitsspeicher pruefen (Memtest86+)\n"
            "sort-key 03\n"
            f"efi      {MEMTEST_EFI}\n"
            "architecture x64\n",
            origin=ORIGIN,
        )

    # Fuer die UEFI-Shell braucht systemd-boot keinen Eintrag: es findet
    # /shellx64.efi auf der Systempartition von selbst.


# ---------------------------------------------------------------------------
# UEFI: GRUB
# ---------------------------------------------------------------------------


def _grub(tree: ProfileTree, settings: ArchisoSettings, menu_title: str) -> None:
    header = f"""# Erzeugt von ArchCustomiser -- nicht von Hand bearbeiten.
insmod part_gpt
insmod part_msdos
insmod fat
insmod iso9660
insmod ntfs
insmod exfat
insmod udf

if loadfont "${{prefix}}/fonts/unicode.pf2" ; then
    insmod all_video
    set gfxmode="auto"
    terminal_input console
    terminal_output console
fi

insmod serial
if serial --unit=0 --speed=115200; then
    terminal_input --append serial
    terminal_output --append serial
fi

default=archcustomiser
timeout={settings.boot_timeout}
timeout_style=menu
"""

    entries = f"""
menuentry "{menu_title} (%ARCH%, UEFI)" --class arch --id 'archcustomiser' {{
    set gfxpayload=keep
    linux /%INSTALL_DIR%/boot/%ARCH%/{settings.vmlinuz} {settings.boot_options()}
    initrd /%INSTALL_DIR%/boot/%ARCH%/{settings.initramfs}
}}

menuentry "{menu_title} (%ARCH%, UEFI) mit Sprachausgabe" --class arch --id 'archcustomiser-speech' {{
    set gfxpayload=keep
    linux /%INSTALL_DIR%/boot/%ARCH%/{settings.vmlinuz} {settings.boot_options()} accessibility=on
    initrd /%INSTALL_DIR%/boot/%ARCH%/{settings.initramfs}
}}
"""

    # GRUB prueft selbst, ob die Datei da ist -- der Eintrag verschwindet
    # automatisch, wenn das Paket fehlt.
    extras = f"""
if [ "${{grub_platform}}" == 'efi' -a -f '{MEMTEST_EFI}' ]; then
    menuentry 'Arbeitsspeicher pruefen (Memtest86+)' --class memtest {{
        set gfxpayload=800x600,1024x768
        linux {MEMTEST_EFI}
    }}
fi

if [ "${{grub_platform}}" == 'efi' ]; then
    if [ -f '/shellx64.efi' ]; then
        menuentry 'UEFI-Shell' --class efi {{
            chainloader /shellx64.efi
        }}
    fi

    menuentry 'UEFI-Firmware-Einstellungen' --id 'uefi-firmware' {{
        fwsetup
    }}
fi

menuentry 'Neu starten' --class reboot {{ reboot }}
menuentry 'Ausschalten' --class shutdown {{ halt }}
"""
    tree.add_file("grub/grub.cfg", header + entries + extras, origin=ORIGIN)

    # loopback.cfg erlaubt es, die ISO-Datei direkt aus einem GRUB-Menue heraus
    # zu starten, ohne sie auf ein Medium zu schreiben. Sie benutzt einen
    # anderen Suchweg: img_dev/img_loop statt archisosearchuuid.
    loopback_options = " ".join(
        [
            "archisobasedir=%INSTALL_DIR%",
            'img_dev=UUID=${archiso_img_dev_uuid}',
            'img_loop="${iso_path}"',
        ]
        + ([f"cow_spacesize={settings.cow_spacesize}"] if settings.cow_spacesize else [])
    )
    tree.add_file(
        "grub/loopback.cfg",
        f"""# Erzeugt von ArchCustomiser.
# Startet die ISO-Datei direkt aus einem GRUB-Menue heraus.
search --no-floppy --set=archiso_img_dev --file "${{iso_path}}"
probe --set archiso_img_dev_uuid --fs-uuid "${{archiso_img_dev}}"

default=archcustomiser
timeout={settings.boot_timeout}
timeout_style=menu

menuentry "{menu_title} (%ARCH%)" --class arch --id 'archcustomiser' {{
    set gfxpayload=keep
    linux /%INSTALL_DIR%/boot/%ARCH%/{settings.vmlinuz} {loopback_options}
    initrd /%INSTALL_DIR%/boot/%ARCH%/{settings.initramfs}
}}
""",
        origin=ORIGIN,
    )
