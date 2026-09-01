"""Einstiegspunkt.

Ohne Argumente startet die grafische Oberflaeche. Mit ``--dry-run`` wird ein
Profil auf der Konsole ausgewertet -- nuetzlich fuer Skripte und um die
Konfiguration ohne Bildschirm zu pruefen.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="archcustomiser",
        description="Erstellt individuelle, auf Arch Linux basierende Live-ISOs.",
    )
    parser.add_argument("--dry-run", metavar="PROFIL", help="Bauplan eines Profils ausgeben")
    parser.add_argument("--check-env", action="store_true", help="Bauumgebung pruefen")
    parser.add_argument(
        "--export-profile",
        metavar="PROFIL",
        help="archiso-Profil aus einem Profil erzeugen",
    )
    parser.add_argument(
        "--out",
        metavar="ZIEL",
        help="Zieldatei (.tar.gz) oder Zielverzeichnis fuer --export-profile",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Ausfuehrliche Ausgabe")
    parser.add_argument("--no-log-file", action="store_true", help="Nicht in eine Datei protokollieren")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from .core.logging_setup import setup_logging

    log_path = setup_logging(verbose=args.verbose, to_file=not args.no_log_file)

    if args.check_env:
        from .core.environment import detect_environment

        environment = detect_environment()
        print(f"Plattform: {environment.platform}")
        print(f"Build moeglich: {'ja' if environment.can_build else 'nein'}")
        print(f"Rechtemodus: {environment.privilege_mode}")
        print(environment.summary())
        for tool in environment.tools:
            mark = "vorhanden" if tool.found else ("FEHLT" if tool.required else "optional, fehlt")
            print(f"  {tool.name:<22} {mark:<16} {tool.purpose}")
        for hint in environment.hints:
            print(f"\nHinweis: {hint}")
        if environment.install_hint():
            print(f"\nInstallieren mit:\n  {environment.install_hint()}")
        return 0 if environment.can_build else 1

    if args.export_profile:
        if not args.out:
            print("Fehler: --export-profile braucht --out", file=sys.stderr)
            return 2
        return _export_profile(Path(args.export_profile), Path(args.out))

    if args.dry_run:
        return _dry_run(Path(args.dry_run))

    if log_path:
        print(f"Protokoll: {log_path}")

    from .gui.app import run

    return run(sys.argv)


def _dry_run(profile_path: Path) -> int:
    from .core.catalog import load_catalog
    from .core.packages import PackageService
    from .core.plan import build_plan, plan_as_text
    from .core.profiles import ProfileError, ProfileService
    from .core.resolver import Resolver

    catalog = load_catalog()
    service = ProfileService(catalog)
    try:
        loaded = service.load(profile_path)
    except ProfileError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    for issue in loaded.issues:
        print(f"[{issue.severity}] {issue.message}", file=sys.stderr)

    resolution = Resolver(catalog).resolve(loaded.config)
    packages = PackageService()
    packages.load()
    report = packages.validate(resolution.package_names)
    plan = build_plan(catalog, loaded.config, resolution, report)
    print(plan_as_text(plan))
    return 0 if plan.can_build else 1


def _export_profile(profile_path: Path, target: Path) -> int:
    """Erzeugt ein archiso-Profil ohne Oberflaeche.

    Ohne Passwort: auf der Kommandozeile gaebe es keinen sicheren Weg, eines
    entgegenzunehmen, und in einem Argument stuende es fuer jeden lesbar in
    /proc. Das Konto wird gesperrt angelegt und laesst sich spaeter mit
    'passwd' freischalten.
    """
    from .core.archiso import DirectorySink, ProfileGenerator, TarSink
    from .core.archiso.errors import ProfileError
    from .core.catalog import load_catalog
    from .core.profiles import ProfileError as ProfileFileError
    from .core.profiles import ProfileService
    from .core.resolver import Resolver

    catalog = load_catalog()
    try:
        loaded = ProfileService(catalog).load(profile_path)
    except ProfileFileError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    resolution = Resolver(catalog).resolve(loaded.config)
    try:
        generated = ProfileGenerator(catalog, loaded.config, resolution).generate()
    except ProfileError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    as_archive = target.suffix in (".gz", ".tgz") or target.name.endswith(".tar.gz")
    if as_archive:
        sink = TarSink(target, root_name=f"{generated.settings.iso_name}-profil")
    else:
        sink = DirectorySink(target, iso_name=generated.settings.iso_name)

    try:
        written = sink.write(generated.tree)
    except ProfileError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    print(f"Profil erzeugt: {written}")
    print(f"  {generated.tree.describe()}")
    print(f"  Ergebnis waere: {generated.iso_filename}")
    for entry in generated.added_packages:
        print(f"  + {entry.name}: {entry.reason}")
    for warning in generated.warnings:
        print(f"  Hinweis: {warning}")
    print()
    print("Auf einem Arch-System:")
    print(f"  {generated.build_command()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
