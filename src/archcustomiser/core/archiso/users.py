"""Benutzerkonto und Passwort-Hash.

Vier Dateien, jede mit einer klaren Aufgabe:

* ``/etc/passwd``  -- root plus unser Benutzer. Wie in archiso/releng nur diese
  Zeilen; alle Systemkonten entstehen zur Bauzeit ueber ``systemd-sysusers``.
  Ausserdem leitet mkarchiso genau daraus das Home-Verzeichnis ab.
* ``/etc/shadow``  -- der Hash. Rechte 0400 ueber ``file_permissions``.
* ``/usr/lib/sysusers.d/…`` -- die Gruppenzugehoerigkeit.
* ``/etc/sudoers.d/10-wheel`` -- Administratorrechte fuer die Gruppe.

**Warum /etc/group nicht angefasst wird:** pacman behandelt es als
``backup``-Datei. Eine eigene Fassung wuerde die Standardgruppen (``root``,
``tty``, ``disk`` …) verdraengen; die Paketfassung landete nur als ``.pacnew``
daneben. archiso/releng liefert deshalb ebenfalls kein ``/etc/group``.

Stattdessen die vorgesehene Loesung: ``sysusers.d`` kennt die Direktive
``m <benutzer> <gruppe>`` -- „add a user to a group, creating both implicitly if
needed". Der ``systemd-sysusers``-Hook von pacman verarbeitet sie waehrend
``pacstrap``. Rein deklarativ, keine Shell, hier vollstaendig pruefbar.

Zum Passwort: Python hat das Modul ``crypt`` in 3.13 entfernt (PEP 594). Die
Kaskade unten kommt ohne aus und gibt das Passwort **niemals** als
Kommandozeilenargument weiter -- argv ist ueber ``/proc/<pid>/cmdline`` fuer
jeden Benutzer des Systems lesbar.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

from ..secrets import Secret
from .errors import HashingUnavailable

log = logging.getLogger(__name__)

DEFAULT_UID = 1000
DEFAULT_SHELL = "/bin/bash"
ROOT_SHELL = "/usr/bin/bash"

# Gesperrtes Konto: ein Passwortfeld, das kein gueltiger Hash sein kann.
LOCKED = "!"


@dataclass(frozen=True, slots=True)
class UserAccount:
    username: str
    uid: int = DEFAULT_UID
    gid: int = DEFAULT_UID
    full_name: str = ""
    shell: str = DEFAULT_SHELL
    sudo: bool = True

    @property
    def home(self) -> str:
        return f"/home/{self.username}"

    def passwd_line(self) -> str:
        """Sieben Felder. Das 'x' bedeutet: das Passwort steht in /etc/shadow."""
        gecos = self.full_name.replace(":", " ").replace("\n", " ")
        return f"{self.username}:x:{self.uid}:{self.gid}:{gecos}:{self.home}:{self.shell}"

    def shadow_line(self, password_hash: str) -> str:
        """Neun Felder.

        Feld 3 ist der Tag der letzten Aenderung, gezaehlt seit dem 1.1.1970.
        Ein leeres Feld dort laesst manche Werkzeuge das Konto als abgelaufen
        ansehen, deshalb wird es gesetzt.
        """
        days = int(datetime.now(timezone.utc).timestamp() // 86400)
        return f"{self.username}:{password_hash}:{days}:0:99999:7:::"


def root_passwd_line(shell: str = ROOT_SHELL) -> str:
    return f"root:x:0:0:root:/root:{shell}"


def root_shadow_line(locked: bool = True) -> str:
    """Root gesperrt lassen.

    archiso/releng laesst root passwortlos (Feld leer), weil die offizielle ISO
    ein Rettungsmedium ist. Fuer ein Desktop-Abbild waere das ein passwortloser
    Administratorzugang -- deshalb hier standardmaessig gesperrt.
    """
    days = int(datetime.now(timezone.utc).timestamp() // 86400)
    return f"root:{LOCKED if locked else ''}:{days}::::::"


def sysusers_line(account: UserAccount, groups: tuple[str, ...] = ("wheel",)) -> str:
    """``m benutzer gruppe`` je Gruppe.

    Kein ``u``-Eintrag: der legt laut Handbuch ein *gesperrtes* Systemkonto an.
    Unsere Benutzerzeile steht bereits in /etc/passwd.
    """
    lines = [
        "# Erzeugt von ArchCustomiser.",
        "# 'm' nimmt einen bestehenden Benutzer in eine Gruppe auf, ohne dass",
        "# /etc/group ueberschrieben werden muss.",
    ]
    for group in groups:
        lines.append(f"m {account.username} {group}")
    return "\n".join(lines) + "\n"


def sudoers_content() -> str:
    return (
        "# Erzeugt von ArchCustomiser.\n"
        "# Diese Datei muss den Modus 0440 haben, sonst verweigert sudo den Dienst.\n"
        "%wheel ALL=(ALL:ALL) ALL\n"
    )


# ---------------------------------------------------------------------------
# Passwort-Hash
# ---------------------------------------------------------------------------


# Groessen aus /usr/include/crypt.h (libxcrypt).
_GENSALT_OUTPUT_SIZE = 192
_CRYPT_DATA_SIZE = 32768


def _hash_via_libcrypt(password: str) -> str | None:
    """Bevorzugter Weg: libxcrypt direkt.

    Kein Subprozess, keine Pipe, kein argv -- der Klartext verlaesst den Prozess
    nie. Auf Arch ist libxcrypt Pflichtabhaengigkeit von pam und shadow und
    damit immer vorhanden.

    Verwendet werden ``crypt_gensalt_rn`` und ``crypt_rn``, nicht das aeltere
    ``crypt``:

    * ``crypt_gensalt_rn(NULL, 0, NULL, 0, …)`` liefert das beste verfuegbare
      Verfahren mit korrekt kodierten Parametern und einem Salt aus der
      Zufallsquelle des Systems. Auf Arch ist das yescrypt -- genau das, was
      ``passwd(1)`` dort ebenfalls erzeugt.
    * ``crypt_rn`` ist threadsicher und meldet Fehler durch ``NULL``. Das
      aeltere ``crypt`` benutzt einen statischen Puffer und gibt im Fehlerfall
      einen mit ``*`` beginnenden String zurueck, was sich schlechter
      auswerten laesst.

    Der Import steht bewusst in der Funktion: unter Windows gibt es die
    Bibliothek nicht, das Modul muss aber importierbar bleiben.
    """
    try:
        import ctypes
        import ctypes.util
    except Exception:
        return None

    candidates = ["libcrypt.so.2", "libcrypt.so.1"]
    try:
        found = ctypes.util.find_library("crypt")
        if found:
            candidates.append(found)
    except Exception:
        pass

    for name in candidates:
        try:
            library = ctypes.CDLL(name, use_errno=True)
        except OSError:
            continue

        try:
            library.crypt_gensalt_rn.argtypes = (
                ctypes.c_char_p, ctypes.c_ulong,
                ctypes.c_char_p, ctypes.c_int,
                ctypes.c_char_p, ctypes.c_int,
            )
            library.crypt_gensalt_rn.restype = ctypes.c_char_p
            library.crypt_rn.argtypes = (
                ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int
            )
            library.crypt_rn.restype = ctypes.c_char_p
        except AttributeError:
            continue

        salt_buffer = ctypes.create_string_buffer(_GENSALT_OUTPUT_SIZE)
        data_buffer = ctypes.create_string_buffer(_CRYPT_DATA_SIZE)
        try:
            # prefix=None -> bestes Verfahren, count=0 -> Standardkosten,
            # rbytes=None -> Zufall vom Betriebssystem.
            salt = library.crypt_gensalt_rn(
                None, 0, None, 0, salt_buffer, _GENSALT_OUTPUT_SIZE
            )
            if not salt:
                continue
            result = library.crypt_rn(
                password.encode("utf-8"), salt, data_buffer, _CRYPT_DATA_SIZE
            )
            if not result:
                continue
            text = result.decode("ascii", errors="replace")
            if not text.startswith("$"):
                continue
            log.debug("Passwort-Hash ueber %s erzeugt", name)
            return text
        except Exception:
            log.debug("crypt_rn ueber %s fehlgeschlagen", name, exc_info=True)
            continue
        finally:
            # Der Ergebnispuffer enthaelt Zwischenwerte der Ableitung.
            ctypes.memset(data_buffer, 0, _CRYPT_DATA_SIZE)
    return None


def _hash_via_openssl(password: str) -> str | None:
    """Rueckfallebene: openssl.

    Das Passwort geht ueber **stdin**, niemals als Argument. openssl beherrscht
    kein yescrypt, liefert also sha512crypt -- von glibc voll unterstuetzt.
    """
    executable = shutil.which("openssl")
    if executable is None:
        return None

    # Auf POSIX wird die Umgebung bewusst beschnitten: Variablen wie LD_PRELOAD
    # oder OPENSSL_CONF koennen das Verhalten eines Prozesses veraendern.
    # Unter Windows fuehrt dasselbe Vorgehen dazu, dass die Programmdatei ihre
    # Bibliotheken nicht mehr findet -- dort wird die Umgebung geerbt.
    env: dict[str, str] | None = None
    if os.name != "nt":
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}

    try:
        result = subprocess.run(
            [executable, "passwd", "-6", "-stdin"],
            input=password,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            shell=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("openssl passwd fehlgeschlagen: %s", exc)
        return None
    if result.returncode != 0:
        return None
    candidate = result.stdout.strip()
    return candidate if candidate.startswith("$6$") else None


def hash_password(password: Secret | str) -> str:
    """Erzeugt einen crypt(3)-Hash. Wirft ``HashingUnavailable``, wenn nichts geht.

    Der Klartext wird nur innerhalb dieser Funktion ausgepackt und nirgends
    protokolliert.
    """
    plain = password.reveal() if isinstance(password, Secret) else str(password)
    if not plain:
        raise HashingUnavailable("leeres Passwort")

    for attempt in (_hash_via_libcrypt, _hash_via_openssl):
        try:
            result = attempt(plain)
        except Exception:
            log.debug("Hash-Verfahren %s fehlgeschlagen", attempt.__name__, exc_info=True)
            result = None
        if result:
            return result

    raise HashingUnavailable(
        "weder libcrypt noch openssl verfuegbar (unter Windows zu erwarten)"
    )


def hashing_available() -> bool:
    """Ob auf diesem System tatsaechlich gehasht werden kann.

    Bewusst ein echter Probelauf und keine blosse Suche im PATH: ein
    vorhandenes ``openssl`` heisst noch nicht, dass es sich aufrufen laesst.
    Waere die Antwort hier optimistischer als die Wirklichkeit, wuerde die
    Oberflaeche ein Passwortfeld anbieten, das beim Erzeugen stillschweigend
    wirkungslos bliebe.

    Die Pruefung laeuft nur auf Anfrage, nicht beim Import -- unter Windows
    muss das Modul importierbar bleiben, obwohl dort meist nichts davon
    vorhanden ist.
    """
    try:
        return bool(hash_password("probe"))
    except Exception:
        return False
