# TsBuckBoost — Projektgedächtnis

Venus-OS-Treiber für den Victron Buck-Boost DC-DC-Wandler (OEM: top systems
TS 400 / TS 800 / TS 1600) plus die 3D-gedruckte Kühlhardware dazu.
Betreiber: Lars, Cerbo GX „einstein" im Wohnmobil, 12 V Starter / 24 V Aufbau.

Sprache im Dialog: **Deutsch**. Alles im Repo — Code, Kommentare, Logmeldungen,
Node-RED-Knotennamen, ReadMe — ist **Englisch**. Das ist bewusst so und bleibt so.

---

## Harte Regel: der Treiber schreibt nicht

Der Treiber sendet **ausschließlich Lesekommandos**: `FE 11` (Lesen: Typ und
Kalibrierung), `FE D0` (Live-Block mit den Messwerten), `FE CF` (Zusatzblock mit
dem CAN-Fühler).

`FE 02`-Schreibzugriffe sind **absichtlich nicht implementiert** und dürfen auch
nicht nachgerüstet werden. Dieselbe Schnittstelle nimmt Parameteränderungen
*und* Firmware-Updates entgegen. Eine falsche Adresse kann Ladeparameter
verstellen oder das Gerät in den Bootloader schicken — an einer Lichtmaschine
im Fahrzeug ist das kein akzeptables Risiko. Konfiguration bleibt bei TSConfig.

Wenn jemand um eine Schreibfunktion bittet: erst auf diese Regel hinweisen.

Seit v1.21 geht jedes Byte an den Wandler durch `send_read()`: nur diese drei
Kommandos, und nur solange die Leitung noch auf 9600 8N1 steht. termios gehört
dem tty, nicht dem Deskriptor — ein Probe-Dienst, der den Port öffnet und seine
Baudrate setzt, stellt sie auch für den Treiber um, und bei 4800 käme `FE CF`
als `F8 FE F8` an (gerechnet im Audit am 18.09.2026, nicht am Gerät gemessen).
Dann wird nichts gesendet, und der Treiber startet neu. `exclusive=True` ist in
pyserial nur ein beratendes flock und hält solche Prozesse nicht ab.

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
version             z.B. v1.21
changes             Changelog, neueste Version oben
setup               SetupHelper-Hook
find-port.sh        listet nur Kandidatenports, das Suchen macht der Treiber
services/TsBuckBoost/run + log/run
extras/nodered-separate-temp-sensors.json
tools/pre-commit    Wächter vor jedem Commit, siehe unten
tools/pre-push      Wächter vor jedem Push, siehe unten
tools/release-check die Prüfung, die beide benutzen
tests/              Tests ohne Venus und ohne Hardware, siehe unten
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
`/dev/serial/by-id/`, CP210x. Der Treiber merkt sich den bestätigten Port in
`/Settings/Devices/tsbuckboost/Port` und fragt, solange der existiert, nur ihn
(vorher `stop-tty.sh`). Nur beim ersten Start, oder wenn er fehlt, fragt er alle
Kandidaten — vorsichtig: Leitung vor der Frage still, genau ein Byte Antwort,
zweimal dasselbe, nur Typen, die er dekodieren kann. Erst dann löst er den Port
vom serial-starter; ein fremdes CP210x-Gerät behält seinen Service. Die
vorgefundene Leitungseinstellung wird nach der Probe zurückgeschrieben. Ohne
Wandler bleibt der Prozess und fragt nach 10 s bis 5 min erneut, ein neuer Port
beendet die Wartezeit. Wird ein Port als Argument übergeben, entfallen Suche,
`stop-tty.sh` und das Merken.

Alte Kurzblock-Typen (TS200/400/800/800C) werden erkannt und nicht angefasst:
kein `stop-tty.sh`, im Log `model not supported`.

Fehlerverhalten: jeder Fehler im Poll beendet den Prozess, damit daemontools
neu startet. Fünf Polls ohne Antwort ebenfalls. Ein Block, der nicht echt sein
kann (über 100 V oder 250 A), zählt wie ein Poll ohne Antwort. Bei
Verbindungsverlust werden alle Messwerte und die Statuspfade ungültig gesetzt;
Strom und Leistung gehen auf 0, der Temperaturalarm bleibt stehen. Vor jedem
Ende wird der Energiezähler gesichert, auch bei SIGTERM von `svc -t`/`svc -d`.
Beendet wird über `exit_process()` mit `os._exit`, das aus jedem Callback
sicher beendet. Fehlen die Settings beim Start, ist das fatal; daemontools
versucht es neu.

Temperaturalarm 75/85 °C mit 5 K Hysterese nach unten. Eine Stufe gilt erst
nach zwei Messungen in Folge und übersteht einen Neustart (Datei unter
`/run/tsbuckboost`).

### Zusätzliche Temperatursensoren

Die Einzeltemperaturen liegen **immer** im eigenen Service des Treibers auf
D-Bus. Der Schalter
`/Settings/Devices/tsbuckboost/SeparateTempSensors`
entscheidet nur, ob Venus sie zusätzlich als **eigene Geräte** listet — im
Alltag macht das die Temperaturansicht am GX unübersichtlich, deshalb aus.

VeDbusService hängt einen Handler an den Rootpfad `/`, davon gibt es genau
einen pro D-Bus-Verbindung. Jeder Zusatzservice braucht deshalb seine eigene
private Verbindung (`private_bus()`). Das war der Bug bis v1.11.

Seit v1.21 startet der Treiber sich selbst neu, wenn sich das Setting ändert —
egal wer es schreibt, Flow oder Konsole. Die GUI muss weiterhin neu gezeichnet
werden, sonst bleiben tote Einträge stehen: `svc -t /service/start-gui` (auf
älterem Venus OS `/service/gui`). Die Instanzen der Zusatzgeräte stehen in
`/Settings/Devices/tsbuckboost_<key>/ClassAndVrmInstance`, vorbelegt 41–44.

### Node-RED

Der Flow in `extras/` schreibt den Setting-Wert und startet die GUI neu; den
Treiber startet das Setting selbst neu (ab v1.21). Die JSON wird nicht von Hand
bearbeitet: Das Audit vom 18.09.2026 hat den Flow neu gebaut, die JS-Texte
stammen aus einem Generator. Wer ihn ändert, prüft mit `tests/test_flow.py`.

Dinge, die Zeit gekostet haben und nicht wieder passieren sollen:

* Der Service-Bezeichner in `victron-input-custom` lautet
  `com.victronenergy.alternator/40` — **mit Schrägstrich**. Die Punktform
  `com.victronenergy.alternator.40` geht über einen Legacy-Pfad, der den
  gecachten Wert nie liefert; die Knoten zeigen dann minutenlang
  „disconnected".
* Der virtuelle Schalter sendet seinen gespeicherten Zustand nach jedem Deploy
  erneut. Bis v1.20 fing das eine Fünf-Sekunden-Sperre ab — am falschen Knoten,
  ein langsamer Boot oder ein Deploy nur des Schalters rutschte durch und
  schrieb den alten Stand ins Setting. Seit v1.21 wird die erste Meldung des
  Schalters nach einem (Neu-)Start mit Lesen des Settings beantwortet, nie mit
  Schreiben; danach zählt nur eine Änderung gegenüber dem zuletzt gesehenen
  Stand als Befehl.
* Befehle laufen nacheinander. Zwei gegenläufige Tipps kurz hintereinander
  erzeugten bis v1.20 eine Endlosschleife aus Treiber- und GUI-Neustarts, weil
  jede Rückmeldung in den Schalter einen neuen Lauf auslöste.
* `svc` endet auch bei einem Fehler mit 0 und meldet ihn nur auf stderr (laut
  Quelltext von daemontools, am GX nicht gemessen). Der Flow wertet deshalb die
  Ausgabe aus, nicht den Exit-Code. Ob Node-RED auf einstein als root läuft und
  `svc` überhaupt darf, ist nicht gemessen.

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
cad/                                        CadQuery-Quellen, DESIGN-NOTES.md
cad/out/                                    erzeugte STEP/STL
```

Seit dem 16.09.2026 committet: der 92-mm-Halter für den Sunon
GF92251B1-000U-AE9, und die Kühlhaube als Entwurf — gerechnet, exportiert, aber
nicht gedruckt. Maße, Verworfenes und die Prüfungen vor einer Freigabe stehen in
`cad/DESIGN-NOTES.md`; die Notizen sind deutsch, anders als der Rest des Repos.

Das Herstellermodell `cad/871efab6-...STEP` gehört **nicht** ins Repo, es ist
nicht unseres zum Weitergeben. Es liegt untracked im Arbeitsbaum und überlebt
den Branchwechsel. Auf `hardware` hält die committete `.gitignore` es draußen,
auf `latest` `.git/info/exclude` — das ist lokal, nicht im Klon, und nach einem
frischen Klon neu einzutragen. Ohne die Datei fällt `duct_concept.py` auf einen
Quader ohne Senkungen zurück; eine Freigängigkeitsprüfung meldet dann die Zapfen
fälschlich als Kollision.

---

## Fallstricke, die schon zugeschlagen haben

**zsh behandelt `#` nicht als Kommentar.** Niemals Befehle mit angehängtem
`# Kommentar` zum Kopieren ausgeben — `git tag  # Liste` wird als
`git tag '#' Liste` ausgeführt.

**macOS-Dateisystem ist nicht case-sensitiv.** Ein `README.md` hat einmal die
`ReadMe.md` auf `latest` überschrieben und den halben Branch geleert. Beim
Kopieren zwischen den Branches auf Groß-/Kleinschreibung achten.

Das gilt dem **Kopieren von Hand**, nicht dem Umschalten. Am 16.09.2026 in
einem Wegwerf-Klon gemessen: `git switch` wechselt sauber zwischen `ReadMe.md`
auf `latest` und `README.md` auf `hardware`, in beide Richtungen, mit leerem
`git status` danach. Ein zweiter Arbeitsbaum dafür ist überflüssig — an dem Tag
wurde einer gebaut und wieder entfernt, weil der Fallstrick falsch gelesen war.

**Heredocs im Terminal brechen bei langem Einfügen ab** (`heredoc>` bleibt
stehen). Inhalte lieber als Datei oder Zip liefern, nicht als Heredoc zum
Einfügen.

**Vor jedem Git-Befehl Verzeichnis und Branch prüfen.** Es gibt mehrere
Projekte nebeneinander; `cd ~/projects/TsBuckBoost && git branch --show-current`
gehört an den Anfang.

**Es gibt genau einen Arbeitsbaum: `~/projects/TsBuckBoost`, klein
geschrieben, beide Branches darin.** In
`~/Projekte` lag bis zum 16.09.2026 ein zweiter, alter Klon: Stand v1.18,
single-branch, seit dem 05.09. nie gefetcht. Eine Übergabe ist dort gelandet,
weil der Pfad aus dem deutschen Wort geraten und nicht geprüft war. Der alte
Klon ist am selben Tag gelöscht worden, nachdem alles daraus hier angekommen
war; `~/Projekte` ist das alte Dokumentenverzeichnis und enthält keinen Code.

**`changes` wird abgeschnitten statt ergänzt.** Zweimal passiert: f797818
(v1.19) ließ von 6660 B nur 976 B übrig, c095815 reparierte es auf 7636 B, und
958dfd0 (v1.20) schnitt erneut auf 723 B. Ein Skript schreibt die Datei, statt
den neuen Eintrag voranzustellen. Alle drei Commits tragen einen
`Claude-Session:`-Trailer und die Zeitzone +0000, sind also in
claude.ai/code-Sitzungen entstanden, wo kein Hook läuft (am 18.09.2026 per
`git log` geprüft). 958dfd0 hat außerdem v1.20 mit `VERSION = "1.19"`
ausgeliefert.

Die erste Fassung des Hooks vom 16.09.2026 prüfte nur die Bytezahl. Am
18.09.2026 in einem Wegwerf-Klon gemessen: Umbenennen (`git mv changes
Changes`), gleich langes Überschreiben und längeres Neuschreiben ließ sie
durch. Seit v1.21 prüft `tools/release-check`:

1. `changes` bleibt unter genau diesem Namen.
2. Alles unterhalb des neuesten Eintrags in HEAD ist Byte für Byte das Ende
   der neuen Datei. Der neueste Eintrag darf noch geändert werden.
3. `version`, `VERSION` in `dbus-tsbb.py` und der oberste Eintrag in `changes`
   nennen dieselbe Version.

`tools/pre-commit` prüft das für jeden Commit in diesem Klon und lässt `tests/`
laufen, wenn Treiber, Flow, Hooks oder Tests betroffen sind. `tools/pre-push`
prüft jeden Commit, bevor er den Klon verlässt — auch solche, die per Pull aus
einer Cloud-Sitzung kamen. Gewollte Änderungen an älteren Einträgen gehen mit
`TSBB_ALLOW_CHANGELOG_EDIT=1 git commit` (die alte Variable
`TSBB_ALLOW_CHANGELOG_SHRINK=1` gilt weiter), Tests überspringen mit
`TSBB_SKIP_TESTS=1`. Gegen eine Versionsabweichung gibt es keinen Schalter.

Gegengeprüft am 19.09.2026: Jede Regel und jeder Fix wurde in einer Kopie
zurückgenommen, und der zugehörige Test wurde rot — 69 Mutationen (Hooks 13,
Treiber 42, Flow 14), jeder Test von mindestens einer erfasst.

Hooks liegen nicht im Klon. Einmal installieren, als Links, damit Änderungen
an `tools/` sofort gelten:

```
ln -sf ../../tools/pre-commit .git/hooks/pre-commit
ln -sf ../../tools/pre-push .git/hooks/pre-push
```

Auf `hardware` fehlt `tools/`; die Links zeigen dort ins Leere, und git
überspringt sie ohne Fehler (am 19.09.2026 mit git 2.54 gemessen). Ein
`git worktree` teilt sich das Hook-Verzeichnis mit dem Hauptbaum.

**Tests.** `python3 -m unittest discover -s tests` auf dem Mac. Der Treiber
läuft dort gegen Attrappen für serial, dbus, gi, vedbus und settingsdevice, mit
falscher Uhr und einem echten Pseudo-Terminal für die Leitungsprüfung; der Flow
in `jsc`, der JavaScriptCore-Shell von macOS, und seine Shell-Befehle unter
`/bin/sh` gegen nachgebaute `dbus`/`svc`. Ohne `jsc` werden die Flow-Tests
sichtbar übersprungen. Am GX laufen die Tests nicht, und sie ersetzen keinen
Versuch am Gerät.

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

multilog beginnt alle 25 kB eine neue Datei; bleibt die Ausgabe stehen, den
Befehl neu starten.

Services und Schalterstand prüfen:

```
dbus -y | grep tsbb
dbus -y com.victronenergy.settings /Settings/Devices/tsbuckboost/SeparateTempSensors GetValue
```

Kommandos in diesem Repo stehen ohne angehängte `#`-Kommentare, damit sie sich
gefahrlos kopieren lassen — siehe den zsh-Fallstrick oben.
