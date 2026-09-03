"""Tests der Oberflaeche.

Bewusst wenige: die Logik steckt in ``core`` und ist dort ohne Qt geprueft.
Hier wird nur getestet, was tatsaechlich an der Oberflaeche haengt -- vor allem
der Signalfluss und die Zusicherung, dass Passwoerter die Konfiguration nie
erreichen.
"""

from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication   # noqa: E402

from archcustomiser.core.config import SelectionSource   # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def store(qapp, catalog):
    from archcustomiser.gui.store import SelectionStore

    return SelectionStore(catalog)


# ---------------------------------------------------------------------------
# Qt-Freiheit des Kerns
# ---------------------------------------------------------------------------


def test_core_does_not_pull_in_qt() -> None:
    """Der Kern muss ohne Bildschirm und ohne Qt testbar bleiben.

    Wird in einem eigenen Prozess geprueft, weil dieser Test selbst Qt geladen
    hat.
    """
    import subprocess

    code = (
        "import sys;"
        "import archcustomiser.core.catalog, archcustomiser.core.resolver,"
        "archcustomiser.core.plan, archcustomiser.core.packages,"
        "archcustomiser.core.profiles, archcustomiser.core.validation;"
        "assert not [m for m in sys.modules if m.startswith('PySide6')], "
        "'core zieht Qt herein';"
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def test_defaults_are_applied_on_start(store) -> None:
    assert "linux" in store.selected("kernel")
    assert "pipewire" in store.selected("audio")


def test_selection_emits_a_signal(store, qtbot=None) -> None:
    received: list[str] = []
    store.selectionChanged.connect(received.append)
    store.toggle("desktop.kde", True)
    assert "desktop" in received


def test_single_selection_replaces_instead_of_adding(store) -> None:
    store.toggle("desktop.kde", True)
    store.toggle("desktop.gnome", True)
    assert store.selected("desktop") == {"gnome"}


def test_multi_selection_accumulates(store) -> None:
    store.toggle("apps.firefox", True)
    store.toggle("apps.git", True)
    assert {"firefox", "git"} <= store.selected("apps")


def test_automatic_entries_are_marked(store) -> None:
    store.toggle("desktop.kde", True)
    assert store.is_auto("display_manager.sddm")
    assert not store.is_auto("desktop.kde")


def test_applying_a_fix_resolves_the_conflict(store) -> None:
    store.set_selection("audio", ["pipewire", "pulseaudio"])
    conflicts = [issue for issue in store.issues() if issue.code == "capability_arity"]
    assert conflicts and conflicts[0].fix

    store.apply_fix(conflicts[0].fix)
    assert not [issue for issue in store.issues() if issue.code == "capability_arity"]


def test_recommendations_are_pre_checked_once_and_stay_removable(store) -> None:
    store.toggle("desktop.kde", True)
    assert store.is_selected("services.bluetooth")

    store.toggle("services.bluetooth", False)
    assert not store.is_selected("services.bluetooth")

    # Eine erneute Auswahl derselben Option darf die Empfehlung nicht
    # zurueckbringen -- sonst laesst sie sich nie abwaehlen.
    store.toggle("apps.firefox", True)
    assert not store.is_selected("services.bluetooth")


# ---------------------------------------------------------------------------
# Passwoerter
# ---------------------------------------------------------------------------


def test_secrets_never_reach_the_configuration(store) -> None:
    store.set_secret("user.password", "hunter2-geheim")
    assert store.has_secret("user.password")
    assert "user.password" not in store.config.fields
    assert "hunter2" not in repr(store.config)


def test_replacing_the_configuration_clears_secrets(store, catalog) -> None:
    from archcustomiser.core.config import BuildConfig

    store.set_secret("user.password", "geheim123")
    store.replace_config(BuildConfig())
    assert not store.has_secret("user.password")


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


@pytest.fixture
def wizard(qapp, catalog, store):
    from archcustomiser.core.packages import PackageConfig, PackageService
    from archcustomiser.core.packages.backend_remote import RemoteIndexBackend
    from archcustomiser.core.profiles import ProfileService
    from archcustomiser.gui.packages_worker import PackageController
    from archcustomiser.gui.wizard import BuildWizard

    from .conftest import FakeTransport

    # Kein Netzzugriff im Test: der Dienst bleibt bewusst ohne Index und meldet
    # damit "nicht pruefbar" statt "existiert nicht".
    service = PackageService(
        PackageConfig(repos=()),
        backend=RemoteIndexBackend(PackageConfig(repos=()), transport=FakeTransport()),
    )
    return BuildWizard(catalog, store, PackageController(service), ProfileService(catalog))


def test_every_visible_category_becomes_a_page(wizard, catalog) -> None:
    from archcustomiser.gui.pages.welcome import WELCOME_STEP

    expected = {category.step for category in catalog.categories if category.visible}
    expected.add(WELCOME_STEP)
    assert set(wizard.pageIds()) == expected


def test_the_wizard_starts_on_the_welcome_page(wizard) -> None:
    """Vorher landete man ohne Vorrede in einem Formular.

    Die vier mitgelieferten Vorlagen waren nur ueber einen Knopf in der
    Fussleiste erreichbar und wurden darum praktisch nie gefunden.
    """
    from archcustomiser.gui.pages.welcome import WelcomePage

    wizard.restart()
    assert isinstance(wizard.currentPage(), WelcomePage)


def test_the_welcome_page_offers_every_bundled_template(wizard) -> None:
    vorlagen = [info for _karte, info in wizard.welcome._choices if info is not None]
    namen = {info.path.stem for info in vorlagen}
    assert {"minimal", "desktop", "gaming", "development"} <= namen


def test_invisible_categories_have_no_page(wizard, catalog) -> None:
    for category in catalog.categories:
        if not category.visible:
            assert category.step not in wizard.pageIds()


def test_driver_page_is_skipped_without_a_graphical_session(wizard, catalog, store) -> None:
    store.set_selection("desktop", ["none"])
    store.set_selection("windowmanager", [])
    apps = catalog.category("apps")
    assert wizard.visible_after(apps) != catalog.category("drivers").step


def test_driver_page_appears_with_a_desktop(wizard, catalog, store) -> None:
    store.toggle("desktop.kde", True)
    apps = catalog.category("apps")
    assert wizard.visible_after(apps) == catalog.category("drivers").step


def test_walking_through_reaches_the_summary(wizard, catalog) -> None:
    wizard.restart()
    wizard.next()                       # ueber die Startseite hinweg
    visited = []
    for _ in range(30):
        page = wizard.currentPage()
        visited.append(page.category.id)
        following = page.nextId()
        if following < 0:
            break
        wizard.next()
    assert visited[0] == "basics"
    assert visited[-1] == "summary"


def test_skipped_steps_are_marked_as_such_in_the_sidebar(wizard, store) -> None:
    """Der irrefuehrende Teil der alten Schrittliste.

    ``nextId()`` ueberspringt Kategorien, deren Bedingung nicht erfuellt ist --
    die Liste zeigte sie aber unveraendert an. Wer keinen Desktop gewaehlt hat,
    wartete so auf die Seite "Grafiktreiber", die nie kommt.
    """
    from archcustomiser.gui.widgets.step_sidebar import StepState

    store.set_selection("desktop", ["none"])
    store.set_selection("windowmanager", [])
    wizard._refresh_sidebar()
    assert wizard.sidebar._states["drivers"] is StepState.SKIPPED

    store.toggle("desktop.kde", True)
    wizard._refresh_sidebar()
    assert wizard.sidebar._states["drivers"] is not StepState.SKIPPED


def test_a_fixed_error_clears_the_mark_again(wizard) -> None:
    """Ein einmal rot markierter Schritt blieb rot, auch nach der Korrektur."""
    from archcustomiser.gui.widgets.step_sidebar import StepState

    wizard.sidebar.set_states({"basics": StepState.ERROR})
    rot = wizard.sidebar._buttons["basics"].styleSheet()
    wizard.sidebar.set_states({"basics": StepState.DONE})
    assert wizard.sidebar._buttons["basics"].styleSheet() != rot


def test_summary_produces_a_plan(wizard, store) -> None:
    store.toggle("desktop.kde", True)
    page = wizard.page(99)
    page.initializePage()
    plan = page.plan()
    assert plan is not None
    assert plan.iso_filename.endswith(".iso")
    assert plan.archinstall["profile_config"]["profile"]["details"] == ["KDE Plasma"]


# ---------------------------------------------------------------------------
# Die Knoepfe muessen tatsaechlich aufrufbar sein
# ---------------------------------------------------------------------------


def test_every_button_signature_actually_matches(qapp, monkeypatch) -> None:
    """Ein Knopf, den kein Test drueckt, kann jahrelang kaputt sein.

    Genau das war der Fall: der Knopf "archiso jetzt installieren" im WSL-Dialog
    uebergab drei Argumente an run_with_wait, das nur zwei annimmt -- ein
    TypeError beim ersten Klick. Kein Test hat ihn je gedrueckt.
    """
    from archcustomiser.core.build import wsl
    from archcustomiser.gui.widgets import wsl_dialog as modul

    aufgerufen: list[str] = []

    def fake_run_with_wait(arbeit, text, *, parent=None, cancellable=True):
        # Signatur wie das Original -- ein zusaetzliches Argument wuerde hier
        # denselben TypeError ausloesen wie in der echten Fassung.
        aufgerufen.append(text)
        return None, None

    monkeypatch.setattr(
        "archcustomiser.gui.widgets.wait_dialog.run_with_wait", fake_run_with_wait
    )

    status = wsl.WslStatus(
        installed=True, distributions=(wsl.Distribution("archlinux", default=True),)
    )
    dialog = modul.WslSetupDialog(status)

    dialog._install_archiso()
    assert aufgerufen, "der Installationsknopf hat run_with_wait nie erreicht"
    assert "archiso" in aufgerufen[0]

    aufgerufen.clear()
    dialog._recheck()
    assert aufgerufen, "der Knopf 'Erneut pruefen' hat run_with_wait nie erreicht"
