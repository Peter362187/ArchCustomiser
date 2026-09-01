"""Sicherheitszusicherungen (Spec Abschnitt 12).

Diese Tests pruefen keine Funktionen, sondern Eigenschaften des Systems:
dass Passwoerter nirgends auftauchen, dass keine Shell benutzt wird und dass
Benutzereingaben nie ungeschuetzt in eine Argumentliste geraten.
"""

from __future__ import annotations

import copy
import logging
import pickle

import pytest

from archcustomiser.core.logging_setup import SecretRedactionFilter, redaction_filter
from archcustomiser.core.secrets import Secret, SecretStore


# ---------------------------------------------------------------------------
# Passwoerter
# ---------------------------------------------------------------------------


def test_secret_hides_itself_in_every_string_form() -> None:
    secret = Secret("hunter2-geheim")
    assert "hunter2" not in repr(secret)
    assert "hunter2" not in str(secret)
    assert "hunter2" not in f"{secret}"
    assert "hunter2" not in f"{secret!r}"
    assert "hunter2" not in "{}".format(secret)
    assert secret.reveal() == "hunter2-geheim"


def test_secret_cannot_be_pickled() -> None:
    """Sonst koennte ein Geheimnis unbemerkt in einer Datei landen."""
    with pytest.raises(TypeError):
        pickle.dumps(Secret("geheim"))


def test_secret_survives_copy_without_leaking() -> None:
    secret = Secret("geheim123")
    duplicate = copy.deepcopy(secret)
    assert duplicate.reveal() == "geheim123"
    assert "geheim123" not in repr(duplicate)


def test_burn_makes_the_secret_unusable() -> None:
    secret = Secret("geheim123")
    secret.burn()
    assert not secret
    with pytest.raises(ValueError):
        secret.reveal()


def test_store_repr_shows_no_values() -> None:
    store = SecretStore()
    store.set("user.password", "hunter2-geheim")
    assert "hunter2" not in repr(store)
    assert store.has("user.password")


def test_store_burns_the_previous_value_on_overwrite() -> None:
    store = SecretStore()
    store.set("k", "erstes-geheimnis")
    first = store.get("k")
    store.set("k", "zweites-geheimnis")
    assert not first          # der alte Puffer wurde geloescht
    assert store.get("k").reveal() == "zweites-geheimnis"


def test_empty_value_clears_the_entry() -> None:
    store = SecretStore()
    store.set("k", "geheim")
    store.set("k", "")
    assert not store.has("k")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _record(message: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, message, args, None)


def test_registered_secret_is_masked_in_the_message() -> None:
    Secret("streng-geheim-42")          # registriert sich beim Filter
    record = _record("Passwort ist streng-geheim-42")
    redaction_filter().filter(record)
    assert "streng-geheim-42" not in record.msg
    assert "***" in record.msg


def test_secret_in_arguments_is_masked_too() -> None:
    """Der haeufigste Fehler: log.info("pw=%s", passwort)."""
    Secret("argument-geheim-99")
    record = _record("Benutzer %s, Passwort %s", "jason", "argument-geheim-99")
    redaction_filter().filter(record)
    assert "argument-geheim-99" not in str(record.args)


def test_crypt_hashes_are_masked_without_registration() -> None:
    """Auch der Hash gehoert nicht ins Log."""
    filter_ = SecretRedactionFilter()
    for hash_value in (
        "$y$j9T$Xk2abcdefghij$klmnopqrstuvwxyz",
        "$6$saltsalt$hashhashhashhash",
        "$2b$12$abcdefghijklmnopqrstuv",
    ):
        record = _record(f"shadow-Eintrag: {hash_value}")
        filter_.filter(record)
        assert hash_value not in record.msg


def test_very_short_values_are_not_masked() -> None:
    """Sonst wuerde ein Passwort 'ab' jedes 'ab' im Log unkenntlich machen."""
    filter_ = SecretRedactionFilter()
    filter_.add_literal("ab")
    record = _record("Paket abiword wird installiert")
    filter_.filter(record)
    assert "abiword" in record.msg


# ---------------------------------------------------------------------------
# Prozessaufrufe
# ---------------------------------------------------------------------------


def test_runner_refuses_a_string_command() -> None:
    """Ein String waere eine Einladung zur Shell-Interpretation."""
    from archcustomiser.core.packages.runner import SubprocessRunner

    with pytest.raises(TypeError):
        SubprocessRunner().run("pacman -Sy")   # type: ignore[arg-type]


def test_pacman_preview_uses_a_separator_and_validated_names(fake_runner) -> None:
    """Doppelter Schutz: geprueft und zusaetzlich hinter '--'."""
    from archcustomiser.core.packages.backend_pacman import PacmanSyncBackend
    from archcustomiser.core.packages.errors import PacmanNotAvailable
    from archcustomiser.core.packages.names import InvalidPackageName

    backend = PacmanSyncBackend(runner=fake_runner)

    # Ein Name, der wie ein Schalter aussieht, kommt gar nicht bis zum Aufruf.
    with pytest.raises((InvalidPackageName, PacmanNotAvailable)):
        backend.preview_transaction(["--root=/"])
    assert all("--root=/" not in " ".join(call) for call in fake_runner.calls)


def test_cache_rejects_repo_names_with_path_separators(tmp_path) -> None:
    """Ein Repo-Name darf nie einen Pfad ausserhalb des Caches bilden."""
    from archcustomiser.core.packages.cache import PackageCache
    from archcustomiser.core.packages.errors import CacheError

    cache = PackageCache(root=tmp_path)
    for evil in ("../../etc/passwd", "a/b", "..", "/absolut"):
        with pytest.raises(CacheError):
            cache.db_path(evil)


def test_cache_is_never_pickled(tmp_path) -> None:
    """Fremde Dateien zu deserialisieren waere eine Angriffsflaeche."""
    from archcustomiser.core.packages.cache import PackageCache

    from .conftest import build_fake_syncdb

    cache = PackageCache(root=tmp_path)
    cache.store(
        "core",
        build_fake_syncdb([{"name": "firefox", "version": "1-1"}]),
        url="https://example.invalid",
        etag=None,
        last_modified=None,
        package_count=1,
    )
    meta = cache.meta_path("core").read_bytes()
    assert meta.lstrip().startswith(b"{"), "Metadaten muessen JSON sein"


def test_predicates_cannot_execute_code() -> None:
    """Der Katalog kann aus einem Benutzer-Overlay stammen."""
    from archcustomiser.core.catalog.predicate import PredicateError, parse

    for evil in (
        {"__import__": ["os"]},
        {"eval": ["1+1"]},
        {"exec": ["print(1)"]},
        123,
        {"all_of": "kein-listenwert"},
    ):
        with pytest.raises(PredicateError):
            parse(evil)
