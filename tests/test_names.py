"""Sicherheitstests fuer die Paketnamenspruefung.

Der wichtigste Test hier ist ``test_invalid_names_never_touch_io``: er beweist,
dass ein boesartiger Name gar nicht erst bis zu einem Prozessstart oder einer
Netzverbindung kommt. Eine Pruefung, die erst *nach* dem Aufruf greift, waere
wertlos.
"""

from __future__ import annotations

import pytest

from archcustomiser.core.packages.errors import InvalidPackageName
from archcustomiser.core.packages.names import (
    is_valid,
    parse_list,
    split_constraint,
    split_provide,
    validate_name,
)

MALICIOUS = [
    "; rm -rf /",
    "$(id)",
    "`id`",
    "&& curl evil.example",
    "| tee /etc/passwd",
    "../../etc/passwd",
    "..\\..\\windows\\system32",
    "/etc/shadow",
    "-Sy",
    "--dbpath=/",
    "--root=/",
    "-",
    "pkg\nrm -rf /",
    "pkg\x00extra",
    "pkg with spaces",
    "ＦＩＲＥＦＯＸ",          # Homoglyphen in voller Breite
    "firefοx",                 # griechisches Omikron statt o
    "",
    "   ",
    ".",
    "..",
    "a" * 200,
    "UPPERCASE",
]

VALID = [
    "firefox",
    "base-devel",
    "python-pip",
    "lib32-mesa",
    "gtk+",
    "gcc-libs",
    "ttf-dejavu",
    "7zip",
    "@invalid-looking-but-allowed",
    "a",
]


@pytest.mark.parametrize("name", MALICIOUS)
def test_malicious_names_rejected(name: str) -> None:
    with pytest.raises(InvalidPackageName):
        validate_name(name)


@pytest.mark.parametrize("name", VALID)
def test_valid_names_accepted(name: str) -> None:
    assert validate_name(name) == name.strip()


def test_invalid_names_never_touch_io(fake_runner, fake_transport) -> None:
    """Ein ungueltiger Name darf weder einen Prozess noch eine Verbindung ausloesen."""
    from archcustomiser.core.packages.validator import classify

    for name in MALICIOUS:
        result = classify(name, index=None, degraded=False)
        # Ohne Index ist die Antwort entweder "ungueltig" oder "nicht pruefbar" --
        # niemals "existiert nicht".
        assert result.kind.name in ("INVALID_NAME", "UNVERIFIED")

    assert fake_runner.calls == [], "es wurde ein Prozess gestartet"
    assert fake_transport.calls == [], "es wurde eine Verbindung geoeffnet"


def test_leading_dash_is_rejected_because_of_argv() -> None:
    """Ein fuehrendes '-' wuerde von pacman als Schalter gelesen."""
    with pytest.raises(InvalidPackageName) as info:
        validate_name("--noconfirm")
    assert "Kommandozeilenschalter" in info.value.reason


def test_split_constraint() -> None:
    assert split_constraint("firefox>=140") == ("firefox", ">=140")
    assert split_constraint("firefox=140.0") == ("firefox", "=140.0")
    assert split_constraint("firefox") == ("firefox", None)


def test_split_provide() -> None:
    assert split_provide("libcap.so=2-64") == ("libcap.so", "2-64")
    assert split_provide("ttf-font") == ("ttf-font", None)


def test_parse_list_accepts_every_separator_users_type() -> None:
    parsed = parse_list("neovim, htop;wget\ncurl\t rsync neovim")
    assert parsed == ["neovim", "htop", "wget", "curl", "rsync"]


def test_parse_list_empty() -> None:
    assert parse_list("") == []
    assert parse_list("   \n  ") == []


def test_is_valid_does_not_raise() -> None:
    assert is_valid("firefox") is True
    assert is_valid("; rm -rf /") is False
