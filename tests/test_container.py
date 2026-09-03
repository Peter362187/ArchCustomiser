"""Tests des Container-Ziels.

Nach dem Muster von ``test_wsl.py``, aber mit einer nachgebildeten Engine statt
einer nachgebildeten Verteilung. Kein Test startet einen Container -- geprueft
wird, dass die richtigen Aufrufe zusammengebaut werden.

Der Container ist der Weg fuer jedes Linux, das kein Arch ist: ``archiso`` ist
in keiner anderen Verteilung paketiert.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import pytest

from archcustomiser.core.build.container import (
    ContainerError,
    ContainerResult,
    ContainerTarget,
    container_name,
    find_engine,
)
from archcustomiser.core.build.targets import ContainerExecutionTarget


class FakeEngine:
    """Zeichnet jede Argumentliste auf und antwortet nach Vorgabe."""

    def __init__(self, antworten: dict[str, ContainerResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.antworten = antworten or {}

    def __call__(self, argv, timeout=None) -> ContainerResult:
        argv = [str(item) for item in argv]
        self.calls.append(argv)
        for schluessel, antwort in self.antworten.items():
            if schluessel in argv:
                return antwort
        return ContainerResult(0, stdout="true")

    def saw(self, *teile: str) -> bool:
        return any(all(t in argv for t in teile) for argv in self.calls)


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def ziel(engine: FakeEngine) -> ContainerExecutionTarget:
    return ContainerExecutionTarget(ContainerTarget("podman", runner=engine))


@pytest.fixture
def vorbereitet(engine: FakeEngine) -> ContainerExecutionTarget:
    """Ein Ziel mit gesetzten POSIX-Pfaden, ohne Dateisystemarbeit.

    Das Container-Ziel weist Windows-Pfade ab -- zu Recht, denn ein Bind-Mount
    unter demselben Pfad ginge dort nicht. Fuer die Pruefung des Aufrufs
    braucht es aber gar kein echtes Verzeichnis.
    """
    ziel = ContainerExecutionTarget(ContainerTarget("podman", runner=engine))
    ziel._work_dir = PurePosixPath("/home/x/work")
    ziel._out_dir = PurePosixPath("/home/x/out")
    ziel._container_name = "archcustomiser-flos-1234"
    return ziel


# ---------------------------------------------------------------------------
# Der Aufruf
# ---------------------------------------------------------------------------


def test_the_call_is_privileged(vorbereitet) -> None:
    """Nicht wegen mkarchiso, sondern wegen pacstrap.

    Dessen chroot_setup haengt acht Dateisysteme in den Zielbaum ein und
    braucht dafuer CAP_SYS_ADMIN. Ohne --privileged scheitert der Bau am
    allerersten Mount.
    """
    argv = vorbereitet.wrap(["mkarchiso", "-v"])
    assert "--privileged" in argv


def test_the_container_gets_a_name(vorbereitet) -> None:
    """Ohne festen Namen gibt es beim Abbrechen nichts zu toeten."""
    argv = vorbereitet.wrap(["mkarchiso"])
    assert "--name" in argv
    name = argv[argv.index("--name") + 1]
    assert name.startswith("archcustomiser-")
    assert "flos" in name


def test_both_directories_are_mounted(vorbereitet) -> None:
    argv = vorbereitet.wrap(["mkarchiso"])
    mounts = [argv[i + 1] for i, teil in enumerate(argv) if teil == "-v"]
    assert len(mounts) == 2
    assert any("/home/x/work" in m for m in mounts)
    assert any("/home/x/out" in m for m in mounts)


def test_host_and_container_paths_are_identical(vorbereitet) -> None:
    """Der ganze Trick des Bind-Mounts.

    Weil beide Seiten denselben Pfad sehen, sind fuenf der sieben
    Protokollmethoden woertlich die von LocalTarget -- und die 166 Zeilen
    Uebertragungscode aus wsl_build.py entfallen ersatzlos.

    Mit festen POSIX-Pfaden geprueft, damit der Test unter Windows dasselbe
    aussagt wie unter Linux.
    """
    argv = vorbereitet.wrap(["mkarchiso"])
    for mount in [argv[i + 1] for i, t in enumerate(argv) if t == "-v"]:
        links, rechts = mount.split(":", 1)
        assert links == rechts.removesuffix(":Z"), "beide Seiten muessen gleich sein"


def test_windows_paths_are_refused(ziel) -> None:
    """Unter Windows staende links ein Laufwerksbuchstabe und rechts ein Pfad
    unterhalb von /mnt.

    Eine Zuordnung, die Docker Desktop selbst vornimmt -- hier produzierte sie
    nur Fehler. Windows hat mit WSL ohnehin den besseren Weg.
    """
    with pytest.raises(ValueError) as info:
        ziel.prepare("flos", Path("C:/Users/x/work"), Path("C:/Users/x/out"))
    assert "WSL" in str(info.value)


def test_environment_goes_through_dash_e(vorbereitet) -> None:
    """Ueber die Systemgrenze erbt der Prozess nichts."""
    argv = vorbereitet.wrap(["mkarchiso"], env={"SOURCE_DATE_EPOCH": "1735689600"})
    assert "-e" in argv
    assert "SOURCE_DATE_EPOCH=1735689600" in argv


def test_an_invalid_variable_name_is_refused(vorbereitet) -> None:
    """Sonst liesse sich ein weiteres Argument einschmuggeln."""
    with pytest.raises(ValueError):
        vorbereitet.wrap(["mkarchiso"], env={"BOESE; rm -rf /": "x"})


# ---------------------------------------------------------------------------
# Abbruch
# ---------------------------------------------------------------------------


def test_cancel_kills_the_container_not_the_client(vorbereitet, engine) -> None:
    """Der Befund, der den Umbau ausgeloest hat.

    ``terminate()`` auf den podman-Prozess traefe nur den Client; der Container
    mit dem laufenden pacstrap ueberlebt ihn im conmon-Baum.
    """
    vorbereitet.cancel_run(None, grace_seconds=0.01)
    assert engine.saw("kill"), "der Container wurde nicht beendet"


@pytest.mark.skipif(os.name == "nt", reason="Container-Ziel weist Windows-Pfade ab")
def test_discard_removes_the_container(ziel, engine, tmp_path) -> None:
    paths = ziel.prepare("flos", tmp_path / "w", tmp_path / "o")
    ziel.discard(paths, keep_work_dir=True, remove_output=True)
    assert engine.saw("rm"), "der Container blieb liegen"


@pytest.mark.skipif(os.name == "nt", reason="Container-Ziel weist Windows-Pfade ab")
def test_discard_never_removes_the_output(ziel, tmp_path) -> None:
    """Die Ausgabe liegt ueber den Bind-Mount schon am Zielort.

    Sie zu loeschen waere hier ein Fehler -- anders als bei WSL, wo die ISO
    drueben nur eine Kopie ist.
    """
    out = tmp_path / "o"
    paths = ziel.prepare("flos", tmp_path / "w", out)
    (out / "fertig.iso").write_bytes(b"x")
    ziel.discard(paths, keep_work_dir=False, remove_output=True)
    assert (out / "fertig.iso").exists()


# ---------------------------------------------------------------------------
# Abbild
# ---------------------------------------------------------------------------


def test_the_image_is_built_only_once(engine) -> None:
    """Das Abbild bei jedem Bau neu zu holen kostete jedes Mal hunderte MB."""
    engine.antworten = {"exists": ContainerResult(1)}
    container = ContainerTarget("podman", runner=engine)
    container.ensure_image()
    assert engine.saw("build")

    engine.calls.clear()
    engine.antworten = {"exists": ContainerResult(0)}
    container.ensure_image()
    assert not engine.saw("build"), "vorhandenes Abbild wurde neu gebaut"


def test_a_failed_image_build_says_why(engine) -> None:
    engine.antworten = {
        "exists": ContainerResult(1),
        "build": ContainerResult(1, stderr="could not resolve host"),
    }
    container = ContainerTarget("podman", runner=engine)
    with pytest.raises(ContainerError) as info:
        container.ensure_image()
    assert "Internetverbindung" in info.value.user_message
    assert "resolve host" in info.value.technical


# ---------------------------------------------------------------------------
# Kleinigkeiten mit Wirkung
# ---------------------------------------------------------------------------


def test_the_container_name_is_safe_and_unique() -> None:
    name = container_name("FLOS Super/Edition 2026")
    assert "/" not in name and " " not in name
    # Zwei Programmfenster duerfen sich nicht gegenseitig den Container toeten.
    assert str(__import__("os").getpid()) in name


def test_a_missing_engine_is_reported_clearly(monkeypatch) -> None:
    monkeypatch.setattr(
        "archcustomiser.core.build.container.shutil.which", lambda _n: None
    )
    assert find_engine() is None
    with pytest.raises(ContainerError) as info:
        ContainerTarget()
    assert "podman" in info.value.user_message


def test_podman_is_preferred_over_docker(monkeypatch) -> None:
    """podman braucht keinen Dienst und laeuft als der aufrufende Benutzer."""
    monkeypatch.setattr(
        "archcustomiser.core.build.container.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    assert find_engine() == "podman"


def test_selinux_mounts_are_labelled(vorbereitet, monkeypatch) -> None:
    """Ohne :Z scheitert der Bau auf Fedora mit "Permission denied"."""
    monkeypatch.setattr(
        "archcustomiser.core.build.container.selinux_active", lambda: True
    )
    argv = vorbereitet.wrap(["mkarchiso"])
    mounts = [argv[i + 1] for i, t in enumerate(argv) if t == "-v"]
    assert all(m.endswith(":Z") for m in mounts)


def test_without_selinux_there_is_no_label(vorbereitet, monkeypatch) -> None:
    monkeypatch.setattr(
        "archcustomiser.core.build.container.selinux_active", lambda: False
    )
    argv = vorbereitet.wrap(["mkarchiso"])
    mounts = [argv[i + 1] for i, t in enumerate(argv) if t == "-v"]
    assert not any(m.endswith(":Z") for m in mounts)
