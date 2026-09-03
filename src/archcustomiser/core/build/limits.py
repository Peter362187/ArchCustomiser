"""Wie viel von diesem Rechner ein Bau nehmen darf.

Am 03.09.2026 hat ein Bau einen Windows-Rechner vollstaendig zum Stillstand
gebracht: kein Fenster liess sich mehr verschieben, der Abbrechen-Knopf war
nicht mehr erreichbar, nur ein harter Neustart half. Die letzte Zeile im
Protokoll war::

    Parallel mksquashfs: Using 12 processors

Das ist die ganze Ursache. mksquashfs startet ohne ``-processors`` einen
Kompressionsfaden je sichtbarem Kern. Da fuer WSL2 ohne ``.wslconfig`` alle
Kerne des Wirts sichtbar sind, saettigte der Bau **jeden** Kern -- und der
Fensterverwalter von Windows, der ebenfalls Rechenzeit braucht, bekam keine
mehr.

**Die Regel: ein Bau bekommt nie den ganzen Rechner.** Das ist keine
Einstellung, sondern eine Zusicherung. Ein Bau laeuft im Hintergrund, waehrend
der Benutzer weiterarbeitet; er darf den Rechner spuerbar auslasten, aber
niemals unbedienbar machen.

**Warum die Haelfte und nicht "alle ausser zwei".** Bei zwoelf Kernen waeren
"alle ausser zwei" zehn gesaettigte Kerne -- das laesst Windows praktisch
genauso wenig Luft wie zwoelf. Die Haelfte ist die kleinste Zahl, bei der die
Bedienbarkeit nicht mehr vom Zufall der Ablaufplanung abhaengt.

**Warum nicht ``nice``.** Naheliegend, aber wirkungslos: ``nice`` ordnet
Prozesse innerhalb *einer* Planungsdomaene. In der WSL-Maschine laeuft ausser
dem Bau nichts, dem er weichen koennte, und der Bedarf, den die Maschine beim
Windows-Planer anmeldet, bleibt Byte fuer Byte derselbe. Dasselbe gilt fuer
eine Prioritaetsklasse auf ``wsl.exe``: die Rechenlast liegt im getrennten
VM-Prozess, nicht im Client. Nur eine echte Obergrenze senkt die Nachfrage.

**Warum nicht ``-mem``.** Der Schalter begrenzt allein die eigenen Caches von
mksquashfs (Vorgabe: ein Viertel des sichtbaren Speichers). Was den Speicher
wirklich fuellt, ist der Seiten-Cache des Gastkernels beim Lesen des
Dateisystems -- den beruehrt ``-mem`` nicht. Weniger Kompressionsfaeden
verringern auch den Durchsatz und damit den Cache-Druck; der Kernschnitt wirkt
also auf beides.
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

# Unterhalb dieser Kernzahl gibt es nichts zu verteilen -- ein einzelner Kern
# bleibt ein einzelner Kern, und ein Bau darauf ist ohnehin zaeh.
MIN_CORES_FOR_SHARING = 3


def cpu_budget(total_cores: int) -> int:
    """Wie viele Kerne ein Bau von ``total_cores`` nehmen darf.

    >>> [cpu_budget(n) for n in (1, 2, 4, 8, 12, 16, 32)]
    [1, 1, 2, 4, 6, 8, 16]

    Die Haelfte, mindestens einer. Bei sehr kleinen Rechnern greift zusaetzlich
    ``total - 1``, damit selbst dort ein Kern frei bleibt.
    """
    if total_cores <= 0:
        raise ValueError(f"unsinnige Kernzahl: {total_cores}")
    if total_cores < MIN_CORES_FOR_SHARING:
        return 1
    return max(1, min(total_cores // 2, total_cores - 1))


def host_cores() -> int:
    """Logische Kerne dieses Rechners. Immer mindestens 1."""
    return max(1, os.cpu_count() or 1)


def host_memory_gb() -> float | None:
    """Arbeitsspeicher dieses Rechners in GB, oder ``None``.

    Ohne Fremdbibliothek und ohne Unterprozess: unter Windows ueber
    ``GlobalMemoryStatusEx``, sonst ueber ``sysconf`` -- das kennen Linux und
    macOS gleichermassen. Wo nichts davon greift, wird nichts behauptet.
    """
    if sys.platform == "win32":
        return _windows_memory_gb()
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, AttributeError):
        return None
    if pages <= 0 or page_size <= 0:
        return None
    return pages * page_size / 1_073_741_824


def _windows_memory_gb() -> float | None:
    import ctypes

    class _MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError):
        return None
    if not ok:
        return None
    return status.ullTotalPhys / 1_073_741_824


def describe_budget(allowed: int, total: int) -> str:
    """Ein Satz fuer Protokoll und Vorabpruefung."""
    return (
        f"{allowed} von {total} Kernen -- der Rest bleibt fuer die Bedienung "
        f"des Rechners frei"
    )
