# TsBuckBoost — Projektgedächtnis

Venus-OS-Treiber für den Victron Buck-Boost DC-DC-Wandler (OEM: top systems
TS 400 / TS 800 / TS 1600) plus die 3D-gedruckte Kühlhardware dazu.
Betreiber: Lars, Cerbo GX „einstein" im Wohnmobil, 12 V Starter / 24 V Aufbau.

Sprache im Dialog: **Deutsch**. Alles im Repo — Code, Kommentare, Logmeldungen,
Node-RED-Knotennamen, ReadMe — ist **Englisch**. Das ist bewusst so und bleibt so.

---

## Harte Regel: der Treiber schreibt nicht

Der Treiber sendet **ausschließlich Lesekommandos**: `FE 11` (Typ),
`FE D0` (Kalibrierung), `FE CF` (Messwerte).

`FE 02`-Schreibzugriffe sind **absichtlich nicht implementiert** und dürfen auch
nicht nachgerüstet werden. Dieselbe Schnittstelle nimmt Parameteränderungen
*und* Firmware-Updates entgegen. Eine falsche Adresse kann Ladeparameter
verstellen oder das Gerät in den Bootloader schicken — an einer Lichtmaschine
im Fahrzeug ist das kein akzeptables Risiko. Konfiguration bleibt bei TSConfig.

Wenn jemand um eine Schreibfunktion bittet: erst auf diese Regel hinweisen.

## Zugangsdaten

Claude hat keine Zugangsdaten für dieses Repo und soll auch keine anfordern.
Commits und Pushes macht Lars selbst auf seinem Mac.

Das Projekt liegt auf **GitHub** und zusätzlich immer als **Kopie auf GitLab**.
Was auf einem landet, gehört auch auf den anderen — beide Branches.

```
origin   git@github.com:mcgyver78/TsBuckBoost.git                      (SSH)
gitlab   git@git.tigerexped.de:tigerexped_playground/TsBuckBoost.git   (SSH)
```

Beide sind seit dem 16.09.2026 in diesem Klon eingetragen. An dem Tag waren sie
deckungsgleich: `latest` 958dfd0, `hardware` a8ecf96. Die tigerexped-Instanz
hört auf Port 2222, der passende Eintrag steht in `~/.ssh/config`.

Ein Push geht nie nur auf eine Seite:

```
git push origin latest && git push gitlab latest
```

---

## Repo-Aufbau

Zwei Branches, bewusst getrennt:

| Branch     | Inhalt |
|------------|--------|
| `latest`   | das SetupHelper-Paket: Treiber, Service, ReadMe, Node-RED-Flow |
| `hardware` | CAD und Schaltpläne. **Nicht** im Paket, damit SetupHelper keine STEP-Dateien auf jedes GX-Gerät kopiert |

Installiert wird über kwindrem/SetupHelper; das Paket landet unter
`/data/TsBuckBoost/`, der Service unter `/service/TsBuckBoost`.

Dateien auf `latest`:

```
dbus-tsbb.py        der Treiber (VERSION-Konstante oben, muss zu `version` passen)
version             z.B. v1.20
changes             Changelog, neueste Version oben
setup               SetupHelper-Hook
find-port.sh        listet nur Kandidatenports, das Suchen macht der Treiber
services/TsBuckBoost/run + log/run
extras/nodered-separate-temp-sensors.json
tools/pre-commit    Wächter gegen das Abschneiden von `changes`, siehe unten
CLAUDE.md           diese Datei, liegt auf beiden Branches
ReadMe.md           zweisprachig, Deutsch und Englisch
```

Bei jeder Änderung am Treiber: `VERSION` in `dbus-tsbb.py`, die Datei `version`
und ein Eintrag in `changes` gehören zusammen angefasst.

---

## Was der Treiber tut

Registriert sich als `com.victronenergy.alternator` — **nicht** als `dcdc`.
Nur so summiert systemcalc `/Dc/Alternator/Power` und das Gerät erscheint auf
der Übersichtsseite neben Solar. Default-Instanz `alternator:40`.

Protokoll: 9600 8N1, DTR+RTS gesetzt, keine Prüfsumme. Port über
`/dev/serial/by-id/`, CP210x. Der Treiber probiert jeden Kandidatenport mit der
Typabfrage und löst nur den vom serial-starter, der antwortet — ein fremdes
CP210x-Gerät behält seinen Service. Wird ein Port als Argument übergeben,
entfallen Probing und `stop-tty.sh`.

Alte Kurzblock-Typen (TS200/400/800/800C) werden beim Start abgelehnt.

Fehlerverhalten: jeder Fehler im Poll beendet den Prozess, damit daemontools
neu startet. Fünf Polls ohne Antwort ebenfalls. Bei Verbindungsverlust werden
alle Messwerte ungültig gesetzt, nicht nur Strom und Leistung.

Temperaturalarm 75/85 °C mit 5 K Hysterese nach unten.

### Zusätzliche Temperatursensoren

Die Einzeltemperaturen liegen **immer** im eigenen Service des Treibers auf
D-Bus. Der Schalter
`/Settings/Devices/tsbuckboost/SeparateTempSensors`
entscheidet nur, ob Venus sie zusätzlich als **eigene Geräte** listet — im
Alltag macht das die Temperaturansicht am GX unübersichtlich, deshalb aus.

VeDbusService hängt einen Handler an den Rootpfad `/`, davon gibt es genau
einen pro D-Bus-Verbindung. Jeder Zusatzservice braucht deshalb seine eigene
private Verbindung (`private_bus()`). Das war der Bug bis v1.11.

Nach dem Umschalten muss der Treiber neu gestartet **und** die GUI neu
gezeichnet werden, sonst bleiben tote Einträge stehen:
`svc -t /service/TsBuckBoost`, dann `svc -t /service/start-gui`
(auf älterem Venus OS `/service/gui`).

### Node-RED

Der Flow in `extras/` schaltet den Setting-Wert und startet Treiber und GUI neu.

Zwei Dinge, die Zeit gekostet haben und nicht wieder passieren sollen:

* Der Service-Bezeichner in `victron-input-custom` lautet
  `com.victronenergy.alternator/40` — **mit Schrägstrich**. Die Punktform
  `com.victronenergy.alternator.40` geht über einen Legacy-Pfad, der den
  gecachten Wert nie liefert; die Knoten zeigen dann minutenlang
  „disconnected".
* Der virtuelle Schalter sendet seinen Zustand direkt nach jedem Deploy erneut.
  Der Flow ignoriert deshalb Nachrichten in den ersten fünf Sekunden nach dem
  Deploy, sonst schreibt er bei jedem Deploy das Setting und startet alles neu.

Die Beschriftungen der Victron-Knoten kommen aus der festen Liste in
`services.json` von `node-red-contrib-victron`. Ein Treiber kann sie nicht
beeinflussen. `/Dc/0/Temperature` heißt dort „Battery temperature 0" — das ist
nicht änderbar, nur umgehbar, indem man andere Pfade nimmt.

---

## Hardware-Branch

```
README.md
fanmount_80mm_BuckBoost50A.step / .stl      Lüfterhalter 80 mm
fanwiring_dcssr_BuckBoost.pdf / .svg        Lüfter über SSR, GPIO-gesteuert
```

Noch nicht committet, liegt aber vor: der 92-mm-Halter für den
Sunon GF92251B1-000U-AE9 und die Kühlhaube. Siehe `cad/DESIGN-NOTES.md`.

---

## Fallstricke, die schon zugeschlagen haben

**zsh behandelt `#` nicht als Kommentar.** Niemals Befehle mit angehängtem
`# Kommentar` zum Kopieren ausgeben — `git tag  # Liste` wird als
`git tag '#' Liste` ausgeführt.

**macOS-Dateisystem ist nicht case-sensitiv.** Ein `README.md` hat einmal die
`ReadMe.md` auf `latest` überschrieben und den halben Branch geleert. Beim
Kopieren zwischen den Branches auf Groß-/Kleinschreibung achten.

**Heredocs im Terminal brechen bei langem Einfügen ab** (`heredoc>` bleibt
stehen). Inhalte lieber als Datei oder Zip liefern, nicht als Heredoc zum
Einfügen.

**Vor jedem Git-Befehl Verzeichnis und Branch prüfen.** Es gibt mehrere
Projekte nebeneinander; `cd ~/projects/TsBuckBoost && git branch --show-current`
gehört an den Anfang.

**Der Arbeitsbaum ist `~/projects/TsBuckBoost`, klein geschrieben.** In
`~/Projekte` lag bis zum 16.09.2026 ein zweiter, alter Klon: Stand v1.18,
single-branch, seit dem 05.09. nie gefetcht. Eine Übergabe ist dort gelandet,
weil der Pfad aus dem deutschen Wort geraten und nicht geprüft war. Der alte
Klon ist am selben Tag gelöscht worden, nachdem alles daraus hier angekommen
war; `~/Projekte` ist das alte Dokumentenverzeichnis und enthält keinen Code.

**`changes` wird abgeschnitten statt ergänzt.** Zweimal passiert: f797818
(v1.19) ließ von 6660 B nur 976 B übrig, c095815 reparierte es auf 7636 B, und
958dfd0 (v1.20) schnitt erneut auf 723 B. Ein Skript schreibt die Datei, statt
den neuen Eintrag voranzustellen.

Dagegen steht seit dem 16.09.2026 `tools/pre-commit`: er bricht jeden Commit ab,
bei dem `changes` kürzer wird als in HEAD. Gegengeprüft, indem die Verkürzung
einmal absichtlich versucht wurde — er hat sie abgewiesen, auch das Löschen der
Datei. Ein gewollter Schrumpf geht mit
`TSBB_ALLOW_CHANGELOG_SHRINK=1 git commit`.

Hooks liegen nicht im Klon, ein frischer Klon hat ihn also nicht. Einmal
installieren:

```
cp tools/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

Ein `git worktree` teilt sich das Hook-Verzeichnis mit dem Hauptbaum, dort ist
nichts extra zu tun.

**`pkill -f <muster>`** trifft auch die eigene Shell, wenn das Muster in deren
Kommandozeile steht. Testsequenzen in ein Skript legen und das killen.

---

## Nützliche Kommandos auf dem GX

Anhalten, starten, neu starten:

```
svc -d /service/TsBuckBoost
svc -u /service/TsBuckBoost
svc -t /service/TsBuckBoost
```

Log mitlesen:

```
tail -f /data/log/TsBuckBoost/current | tai64nlocal
```

Services und Schalterstand prüfen:

```
dbus -y | grep tsbb
dbus -y com.victronenergy.settings /Settings/Devices/tsbuckboost/SeparateTempSensors GetValue
```

Kommandos in diesem Repo stehen ohne angehängte `#`-Kommentare, damit sie sich
gefahrlos kopieren lassen — siehe den zsh-Fallstrick oben.
