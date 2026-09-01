# ArchCustomiser

Grafischer Builder für eigene, auf Arch Linux basierende Live-ISOs.

Der Benutzer klickt sich durch einen Wizard — Desktop, Kernel, Programme,
Netzwerk, Audio, Sprache, Branding — und erhält am Ende eine bootfähige ISO.
Kenntnisse über `archiso`, `pacman` oder die interne ISO-Struktur sind nicht
nötig.

Das Programm baut Arch Linux **nicht nach**. Es ist eine Automatisierungsschicht
über der offiziellen Infrastruktur: `archiso`, `pacman`, die offiziellen
Repositories, `systemd` und `archinstall`. Die Abhängigkeitsauflösung macht
pacman, nicht dieses Programm.

---

## Stand der Umsetzung

| Phase | Inhalt | Status |
|-------|--------|--------|
| 1 | Projektstruktur, GUI-Gerüst, Umgebungserkennung, Logging | fertig |
| 2 | Katalog, Datenmodell, Resolver, generische Wizard-Seiten | fertig |
| 3 | Profile speichern, laden, migrieren | fertig |
| 4 | Paketvalidierung gegen die echten Arch-Repositories | fertig |
| 5 | archiso-Profil erzeugen | fertig |
| 6 | ISO-Build ausführen (`mkarchiso` starten) | fertig |
| 7 | Logging und Fehlerbehandlung | fertig |
| 8 | Branding | fertig |
| 9 | Tests | laufend (362) |
| 10 | UI/UX und Dokumentation | laufend |

**Der Funktionsumfang ist vollständig:** Wizard, Profile, Paketprüfung, Dry-Run,
Profilerzeugung und der ISO-Build mit Fortschrittsanzeige, Abbruch und Protokoll.

**Eine echte ISO wurde gebaut.** Der vollständige Ablauf ist über die
Programmschnittstelle durchlaufen worden — Profil erzeugen, in eine
WSL-Arch-Verteilung übertragen, `mkarchiso` ausführen, ISO zurückholen:

```
Datei        : miniarch-1.0-x86_64.iso (1311 MB)
ISO-9660     : gültig (CD001-Signatur)
Datenträger  : MINIARCH_1_0
MBR-Signatur : 0x55AA vorhanden → BIOS-startfähig
Dauer        : rund 3 Minuten
```

**Was noch aussteht:** der Boot-Test von echter Hardware oder aus einer
virtuellen Maschine.

---

## Voraussetzungen

### Zum Bedienen (jede Plattform)

* Python 3.11 oder neuer
* PySide6, PyYAML, Jinja2

Konfiguration, Profile, Paketprüfung und Dry-Run funktionieren unter Windows,
macOS und Linux gleichermaßen.

### Zum Bauen einer ISO unter Windows

Einmalig, in der PowerShell **als Administrator**:

```bash
wsl --install archlinux
```

Nach dem Neustart in Arch:

```bash
sudo pacman -Syu --needed archiso
```

Das Programm erkennt das selbst und führt beim ersten „ISO erstellen" durch
diese Schritte. Platzbedarf: WSL legt seine virtuelle Platte auf `C:` ab, für
ein Desktop-Abbild mit Spielen werden dort 25–40 GB gebraucht.

### Zum Bauen einer ISO (direkt auf Arch Linux)

```bash
sudo pacman -S --needed archiso arch-install-scripts squashfs-tools libisoburn dosfstools mtools grub openssl
```

Das Programm prüft das beim Start selbst und nennt fehlende Pakete samt
Installationsbefehl. Prüfen lässt sich das auch ohne GUI:

```bash
python -m archcustomiser --check-env
```

**Root wird nicht benötigt.** Seit archiso 89 kapselt `mkarchiso` die
privilegierten Schritte in `unshare --map-auto --map-root-user`. Dafür braucht
der aufrufende Benutzer allerdings Sub-ID-Bereiche:

```bash
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER
```

Fehlen sie, weicht das Programm auf `pkexec` aus und sagt das auch.

**Plattenplatz:** Das Arbeitsverzeichnis braucht für ein Desktop-Image mit
Spielen realistisch 25–40 GB und muss auf einem Linux-Dateisystem liegen.

---

## Installation

```bash
git clone <repository> && cd ArchCustomiser
python -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"
```

Unter Windows entsprechend `.venv\Scripts\pip`.

---

## Verwendung

```bash
python -m archcustomiser
```

Weitere Aufrufformen:

```bash
python -m archcustomiser --dry-run profiles/gaming.yaml
```

```bash
python -m archcustomiser --check-env
```

```bash
python -m archcustomiser --export-profile profiles/gaming.yaml --out ~/flos-profil.tar.gz
```

Der Wizard führt durch dreizehn Schritte. Seiten, die nicht zutreffen, werden
übersprungen — ohne Desktop und ohne Window Manager erscheint zum Beispiel die
Treiberseite gar nicht erst.

---

## Vom Wizard zur ISO

**Auf einem Arch-System** genügt „ISO erstellen". Davor erscheint eine
Vorabprüfung — Werkzeuge, Rechte, Plattenplatz, Dateisystem — die alle Befunde
auf einmal zeigt, statt nach jeder Korrektur den nächsten Fehler. Danach läuft
der Build mit Fortschrittsbalken, abgehakter Schrittliste und mitlaufendem
Protokoll. Abbrechen ist jederzeit möglich.

Der Fortschritt kommt nicht aus einer Schätzung: `mkarchiso` meldet jeden
Abschnitt, und innerhalb der beiden langen Phasen zählt pacman die Pakete
während `mksquashfs` und `xorriso` Prozente melden.

**Auf Windows** baut das Programm über WSL — ein Linux innerhalb von Windows,
kein zweiter Rechner und kein Dual-Boot. Beim ersten Mal führt ein Dialog durch
die Einrichtung (zwei Befehle zum Kopieren); danach genügt ebenfalls „ISO
erstellen". Das Profil wandert als Archiv hinüber, wird dort ausgepackt und
gebaut, und die fertige ISO landet wieder in deinem Windows-Ordner.

Warum der Umweg über ein Archiv: Unter `/mnt/c` liegt ein Windows-Dateisystem
ohne symbolische Verknüpfungen — und ein archiso-Profil besteht zu einem
Drittel daraus. Direkt dorthin geschrieben bräche der Build ab.

**Auf jedem anderen System** bietet das Programm den Profilexport an — als
`.tar.gz` oder als Ordner.

Danach auf einem Arch-System:

```bash
tar xzf flos-profil.tar.gz && cd flos-profil && mkarchiso -v -w ../work -o ../out .
```

Ergebnis: `../out/flos-1.0-x86_64.iso`.

Zwei Dinge, die dabei überraschen können:

**Das Archiv muss auf dem Linux-System entpackt werden.** Unter Windows bricht
`tar` ab, weil ein archiso-Profil Verknüpfungen auf Pfade wie
`/usr/lib/systemd/system/sddm.service` enthält, die es dort nicht gibt. Das
offizielle archiso-Repository verhält sich exakt genauso — es ist keine
Eigenart dieses Programms.

**Root wird nicht gebraucht.** Seit archiso 89 kapselt `mkarchiso` die
privilegierten Schritte selbst; nötig sind nur Sub-ID-Bereiche (siehe
Voraussetzungen).

Die Registerkarte **„Profildateien"** in der Zusammenfassung zeigt den
vollständigen Baum, bevor eine einzige Datei entsteht — mit Pfad, Größe und der
Katalogoption, die jede Datei beigesteuert hat.

### Was das Programm automatisch ergänzt

Der Katalog enthält nur, was zur Auswahl steht. Zum Booten fehlen dann Pakete,
die keine Wahlmöglichkeit sind: `base`, `mkinitcpio`, `mkinitcpio-archiso`, und
je nach Bootmodus `syslinux`. Diese ergänzt der Generator — jedes mit einer
Begründung, die in der Paketliste und im Dry-Run steht.

Ebenso wird `[multilib]` in der erzeugten `pacman.conf` aktiviert, sobald Steam
oder ein anderes 32-Bit-Paket gewählt ist. In der archiso-Vorlage ist der
Abschnitt auskommentiert; ohne diesen Schritt bräche der Build an einem nicht
gefundenen Paket ab.

---

## Profile

Ein Profil hält die Auswahl fest und lässt sich jederzeit wieder laden.
Mitgeliefert werden `minimal`, `desktop`, `gaming` und `development` im
Verzeichnis `profiles/`. Eigene Profile landen unter
`~/.config/archcustomiser/profiles/`.

```yaml
schema_version: 1
catalog_version: "2026.09.01"
name: Gaming

selections:
  desktop: [kde]
  kernel: [linux-zen]
  audio: [pipewire]
  apps: [firefox, steam, lutris, gamescope]
  services: [bluetooth]

fields:
  basics.hostname: arch-gaming
  basics.locale: de_DE.UTF-8
  branding.distro_name: CustomArch Gaming
```

Drei Eigenschaften, die im Alltag zählen:

**Automatische Ergänzungen werden nicht gespeichert.** KDE zieht SDDM nach sich,
aber im Profil steht nur KDE. Bringt eine spätere Katalogversion einen anderen
Login-Screen mit, übernimmt ein altes Profil ihn automatisch — statt eine
Entscheidung von 2026 festzuschreiben.

**Passwörter stehen nie drin.** Sie liegen ausschließlich im Speicher und
erreichen die Konfigurationsstruktur gar nicht erst. Steht in einer von Hand
bearbeiteten Datei doch eines, wird es beim Laden verworfen und gemeldet.

**Unbekannte Einträge gehen nicht verloren.** Ein Profil, das mit einer
Katalogerweiterung erstellt wurde, behält seine Einträge auch dann, wenn es auf
einem Rechner ohne diese Erweiterung geöffnet und gespeichert wird.

---

## Eigene Pakete

Auf der Seite „Zusätzliche Pakete" lässt sich frei eingeben. Jede Zeile wird
sofort gegen die echten Repositories geprüft und eingeordnet:

| Anzeige | Bedeutung |
|---|---|
| `extra/neovim 0.12.5-1, 31 MB` | gefunden |
| `Paketgruppe mit 70 Paketen` | eine Gruppe wie `plasma` |
| `wird bereitgestellt von noto-fonts` | virtuelles Paket mit einem Anbieter |
| `11 Anbieter — bitte einen wählen` | mehrdeutig, Auswahl nötig |
| `nicht gefunden. Meinten Sie: neovim?` | Tippfehler mit Vorschlag |
| `nicht prüfbar` | keine Paketdaten verfügbar |

Zur letzten Zeile: **Solange keine vollständigen Paketdaten vorliegen, behauptet
das Programm nie, ein Paket existiere nicht.** Andernfalls würde ein
Netzwerkausfall dazu führen, dass jemand einen völlig korrekten Paketnamen
löscht, weil das Programm ihn als Tippfehler ausgibt.

Gruppen werden bewusst **nicht** in Einzelpakete aufgelöst, bevor sie in die
Paketliste wandern. `packages.x86_64` akzeptiert Gruppennamen, und pacstrap löst
sie zur Bauzeit auf dem dann aktuellen Stand auf. Eine hier eingefrorene
Mitgliederliste wäre beim nächsten Repo-Update bereits veraltet.

---

## Eigenes Branding

Einstellbar sind Distributionsname, Version, Logo, Hintergrundbild und
Boot-Splash. Daraus ergeben sich automatisch:

* ISO-Dateiname — `FLOS` + `1.0` → `flos-1.0-x86_64.iso`
* Datenträgerbezeichnung — `FLOS_1_0` (ISO-9660: nur `A-Z0-9_`, max. 32 Zeichen)
* Verzeichnis auf der ISO — `flos` (mkarchiso erlaubt nur `[a-z0-9]`, max. 30)
* `/etc/os-release`, Bootmenü, Login-Screen, Desktop-Hintergrund

### Zur Herkunftsangabe

Das System bleibt erkennbar arch-basiert: `/etc/os-release` bekommt
`ID_LIKE=arch` und `PRETTY_NAME="FLOS 1.0 (based on Arch Linux)"`. Das ist der
in `os-release(5)` vorgesehene, maschinenlesbare Herkunftsnachweis.

Namen, die sich als Arch Linux selbst ausgeben, werden abgelehnt. Namen, die mit
„Arch" beginnen, lösen eine Warnung aus: die Arch-Markenrichtlinie (Fassung
2021-04-18) stuft solche Namen als verwechselbar ein. Ausdrücklich erlaubt ist
dagegen der Zusatz „based on Arch Linux".

---

## Fehlerbehebung

**„Ein ISO-Build ist nur unter Linux möglich"**
Erwartet, wenn nicht unter Arch gearbeitet wird. Alles außer dem Build
funktioniert trotzdem vollständig.

**„Die Paketdaten sind X Tage alt"**
Auf der Paketseite „Paketdaten aktualisieren" anklicken. Die Anzeige nennt den
Stand der Repositories, nicht den Zeitpunkt der letzten Abfrage.

**„Keine Verbindung zu den Arch-Paketservern"**
Der Wizard bleibt vollständig bedienbar; Paketnamen werden dann als „nicht
prüfbar" geführt. Falsch geschriebene Namen fallen in diesem Fall erst beim
Build auf.

**„Es fehlen benötigte Werkzeuge"**
`python -m archcustomiser --check-env` nennt jedes fehlende Paket und einen
fertigen Installationsbefehl.

**„Für einen Build ohne Root-Rechte werden Sub-ID-Bereiche benötigt"**
Siehe `usermod`-Befehl unter Voraussetzungen. Alternativ läuft der Build über
`pkexec`.

**Ein Paket wird als „mehrdeutig" gemeldet**
Der Name ist ein virtuelles Paket mit mehreren Anbietern. pacman würde hier
nachfragen — `mkarchiso` läuft aber ohne Rückfrage und würde abbrechen. Deshalb
muss der Anbieter vorher feststehen.

**Logdatei**
Linux: `~/.local/state/archcustomiser/archcustomiser.log`
Windows: `%LOCALAPPDATA%\ArchCustomiser\State\archcustomiser.log`
Passwörter und Passwort-Hashes werden dort maskiert.

---

## Architektur

```
src/archcustomiser/
├── core/                    komplett ohne Qt -- ohne Bildschirm testbar
│   ├── catalog/             YAML-Modell, Lader, Prädikate
│   ├── packages/            Paketvalidierung (siehe unten)
│   ├── config.py            BuildConfig -- die Auswahl des Benutzers
│   ├── resolver.py          Auflösung zu Paketen, Diensten, Dateien
│   ├── profiles.py          Speichern, Laden, Migrieren
│   ├── archiso/             Profilerzeugung: Baum, Ausgabewege, Bootloader
│   ├── build/               ISO-Bau: mkarchiso, Fortschritt, WSL-Anbindung
│   ├── plan.py              Bauplan und archinstall-Konfiguration
│   ├── validation.py        Feldprüfungen
│   ├── environment.py       Werkzeug- und Rechteerkennung
│   ├── secrets.py           Passwortbehandlung
│   └── logging_setup.py     Logging mit Maskierung
├── gui/                     PySide6
│   ├── store.py             einzige Stelle, die Konfiguration verändert
│   ├── wizard.py            QWizard, Seitenreihenfolge, Profile
│   └── pages/               vier generische Seitentypen
data/catalog/                der gesamte Optionsumfang als YAML
profiles/                    mitgelieferte Profile
tests/                       362 Tests, ohne Netz und ohne Bildschirm
```

Ausführlicher in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

### Der Katalog ist das Programm

Die Oberfläche kennt keine einzige Desktop-Umgebung namentlich. Es gibt vier
Seitentypen (`selection`, `form`, `free_packages`, `summary`); alles andere ist
YAML. Eine neue Desktop-Umgebung, ein neuer Kernel, ein neues Eingabefeld oder
eine komplette neue Kategorie ist ein Eintrag in `data/catalog/` — ohne eine
Zeile Python.

---

## Tests

```bash
.venv/bin/python -m pytest -q
```

Die Testsuite läuft ohne Netzwerkzugriff und ohne Bildschirm. Der ALPM-Parser
wird gegen **echte** `tar.gz`-Archive geprüft, nicht gegen Attrappen — so fällt
eine Formatänderung bei pacman auf.

```bash
.venv/bin/python -m pytest -m network
```

Zusätzliche Tests gegen die echten Arch-Server; standardmäßig abgewählt.

---

## Lizenz und Verhältnis zu Arch Linux

Dieses Projekt ist nicht mit dem Arch-Linux-Projekt verbunden und wird nicht von
ihm unterstützt. „Arch Linux" ist eine Marke des Arch-Linux-Projekts.
