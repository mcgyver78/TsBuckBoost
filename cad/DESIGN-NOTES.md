# Kühlhardware für den Buck-Boost 50 A — Entwurfsstand

Stand 16.09.2026. Alles in diesem Ordner ist CAD und gehört auf den Branch
`hardware`, nicht ins SetupHelper-Paket.

Zwei Teile:

* **Lüfterhalter** (`fanmount.py`) — fertig, 80 mm ist committet, 92 mm nicht
* **Kühlhaube** (`duct_concept.py`) — Entwurf, noch nicht gedruckt

---

## Der Converter, ausgemessen

Alle Maße stammen aus dem Herstellermodell
`871efab6-50ABuckBoostDCDCconverterstep.STEP`, nachgemessen mit CadQuery.
Nicht aus Datenblättern, nicht geschätzt.

Die Datei selbst liegt **nicht** im Repo — sie ist nicht unsere, um sie
weiterzugeben, und `.gitignore` hält sie draußen. Wer die Prüfungen unten fahren
will, legt sie neben die Skripte; ohne sie greift der Quader-Ersatz, siehe
„Skripte".

```
Körper      X -96.5 .. 22.5    Y 0 .. 37    Z -109.9 .. 103.2
Bohrbild    X -89.95 / 16.05   Z -103.41 / 96.59
Rippen      2,4 mm hoch, ~4 mm breit, 10 mm Teilung, längs, auf BEIDEN Seiten
```

**Die beiden Seiten sind nicht gleich, und das ist der wichtigste Punkt.**

| | Seite A | Seite B |
|---|---|---|
| Bohrung | ⌀5,52 durchgehend | ⌀5,52 durchgehend |
| drumherum | freie **⌀15,5-Senkung, 22,5 mm tief** unter den Rippenspitzen, gefräste Auflagefläche 2,4 mm unter den Spitzen | plane, gefräste **25,9 mm breite Fläche**, läuft längs durch alle vier Montagepunkte (X −95,9…−70,0 und −4,0…+22,0) |

Im STEP ist Seite A die Y-0-Seite, Seite B die Y-37-Seite.

Die Senkung ist 22,5 mm tief ab Rippenspitze, 20,1 mm ab der Auflagefläche.
**20,1 ist exakt `POST_STEP` im Lüfterhalter** — der ⌀12-Pfosten des Halters
steckt in dieser Senkung, `SCREW_HEAD_Z = 21.6` ist der Schraubenkopf knapp
darüber. Der Lüfterhalter gehört also auf Seite A, und die Kühlhaube auch.

Weiter unten in der Bohrung: ⌀10,8 von 22,5 bis 27,5, dann die ⌀5,52 durch bis
zur anderen Seite.

Gemessene lichte Weite der Senkung je Loch: 15,47 / 15,61 / 15,80 / 15,97 mm.

**Ein Guss-Merkmal neben einem der vier Löcher lässt die Auflagefläche nur bis
⌀16,5 frei.** Deshalb ist die Schulter der Haube ⌀16 und nicht ⌀18 wie beim
Lüfterhalter. Nachgemessen an allen vier Löchern, drei sind bis ⌀26 frei.

---

## Kühlhaube — Aufbau

Der Converter steht auf vier losen Distanzstücken an seinen eigenen
Montagepunkten. Die Montagefläche selbst ist der Boden des unteren Kanals —
eine durchgehende Grundplatte gibt es bewusst nicht, die existiert schon.

Der Lüfter drückt von oben in ein Plenum über den Rippen. Ein Kanal an der
linken Längsseite führt einen Teil der Luft nach unten unter das Gerät, sodass
beide Seiten angeströmt werden. Ausgeblasen wird an den beiden Stirnseiten;
seitlich ist nur links Platz.

Ein M5 je Ecke geht von oben durch Haubensäule, Converter und loses
Distanzstück in die Montagefläche — eine durchgehende Verschraubung.

### Die vier Säulen

Nach dem Vorbild der Pfosten im Lüfterhalter:

```
⌀12 Zapfen, 19,1 mm      in die ⌀15,5-Senkung des Converters
⌀16 Schulter             sitzt auf der gefrästen Fläche, 2,4 mm unter den Spitzen
                         und läuft bis in die Platte
Gesamtlänge              34 mm
```

Der Zapfen endet 1 mm über dem Senkungsgrund. Die Schulter ist damit das
einzige Maß — der Lüfterhalter legt beide auf dasselbe Maß, was zwei Anschläge
gegeneinander arbeiten lässt.

Die Säulen sind **fest Teil der Haube** und werden mit ihr gedruckt. Nur die
Distanzstücke unter dem Converter sind lose. Das war eine ausdrückliche
Festlegung.

**Außer den vier Schultern berührt nichts der Haube den Converter.** Geprüft
gegen das echte, gewendete Herstellermodell: 0,0000 mm³ Kollision, Auflage
340,6 mm² auf den vier gefrästen Flächen.

### Strömungsgeometrie

Der Querschnitt ist ein einziges gezogenes Profil mit Radien, keine Kästen:

```
R12   Plenum knickt in den Seitenkanal ab (Außenseite des Bogens)
R18   Kanal knickt unter den Converter (Außenseite)
R8    Stirnwand läuft nicht in eine rechtwinklige Sackgasse
```

Scharfer Gehrungsbogen kostet rund K = 1,1…1,3 Staudrücke, ein Bogen mit
r/d ≈ 0,7 etwa K = 0,3. Daher die Radien.

Die Lüfterbohrung öffnet sich konisch nach unten (⌀88 → ⌀94 über 4 mm), damit
der Strahl nicht an einer scharfen Kante abreißt.

Plenum **8 mm** über den Rippen. Das ist der Kern: die Rippen sind nur 2,4 mm
hoch, eng heißt also, die Luft läuft an der Oberfläche statt darüber. 5,3 statt
3,5 m/s, h von rund 21 auf 30 W/m²K. Diese 8 mm nicht aufweichen.

Austritte von 8 auf 12 mm über die letzten 30 mm geöffnet, Decke und
Außenfläche steigen gemeinsam an, damit die Platte 4 mm dünn bleibt. Holt
einen Teil des Austrittsstaudrucks zurück.

Die Wände enden 2 mm über der Montagefläche, darunter ein Schaumstreifen —
dichtet und gleicht Unebenheiten aus. Mit 8-mm-Distanzstücken stehen sie auf,
mit 12 mm bleiben 4 mm für den Streifen.

Erwartung: Übertemperatur von rund 30 K auf 18–20 K. Abschätzung nach
Lehrbuchkorrelationen (Dittus-Boelter), die Messung im Betrieb entscheidet.

### Abmessungen

```
Haube        151,9 × 61,0 × 216,0 mm     217,5 cm³
Distanz      ⌀13, in 8 / 10 / 12 mm      3,5 / 4,3 / 5,2 cm³
```

---

## Druck

Drucker: Creality CR-10 V2, 0,4 mm Düse, Cura 5.8.

**Material: GreenTEC Pro, getempert.** Die Haube sitzt über Rippen, die 75 °C
erreichen, die Luft darin ist wärmer. PLA scheidet aus.

**Orientierung: stehend auf einer Stirnseite, 216 mm hoch.** Das gezogene
Profil läuft bereits entlang Z, `print_hood.stl` liegt deshalb schon richtig
auf z = 0 — nichts drehen. In dieser Lage ist der Körper ein konstanter
Querschnitt: alle Wände senkrecht, kein Support, und die Schichtlinien laufen
quer zum Luftweg statt längs. Eine schwache Schicht kann so keinen Leckspalt
den Kanal entlang aufreißen.

Was in der Geometrie schon für den Drucker erledigt ist:

* Wände 3,2 mm = 8 Linien à 0,4. Mit **Wall Line Count = 4** reines Perimeter.
* Flache Auflage (⌀14) um jede Schraube — die Außenfläche ist dort geneigt.
* Waagerechte Löcher 0,2 mm größer, weil ihr Scheitel durchhängt:
  M5 5,8 statt 5,6, Lüfterschrauben 4,7 statt 4,5. Die Distanzstücke stehen
  beim Drucken aufrecht und behalten 5,6.
* Brim nehmen, der Fußabdruck ist ein dünner Ring.

Einziger echter Überhang sind die Säulen, die mit ihrer vollen Länge an der
Platte ansetzen. Liegt innen im Plenum auf Flächen, die nichts berührt. Wer es
sauber will: Support-Blocker über den Rest des Modells, nur die vier Säulen
stützen lassen.

`print_spacers_*.stl` enthält die vier Distanzstücke aufrecht und dicht
beieinander, damit sie als kompakter kleiner Druck laufen.

---

## Was verworfen wurde, und warum

Damit es nicht noch einmal vorgeschlagen wird:

**Zentrierzapfen in die Montagebohrung.** Geht nicht. Die Bohrung ist ⌀5,52 und
der M5 muss durch. Ein Zapfen darin hätte 0,15 mm Wandstärke.

**Durchgehende Grundplatte unter dem Converter.** Ausdrücklich gestrichen — die
Fläche, auf der das Gerät montiert wird, ist schon der Boden.

**Stützkeile neben den Säulen.** Waren als Druckhilfe drin, lagen aber mit
ihrer Unterkante auf y = 37, also direkt auf den Rippen. Damit hätte der
Converter teilweise auf den Keilen gehangen statt an den Schrauben. Raus.

**Zweiter Lüfter, PWM-Regelung.** Ausgeschlossen.

**Plenum aufweiten, um die Säulen zu verlängern.** War ein Zwischenschritt
(`EXIT_RISE` auf 12 mm) und ist wieder raus, seit die Länge aus der Senkung
kommt. Ein größeres Plenum kostet Strömungsgeschwindigkeit und damit genau die
Kühlleistung, um die es geht.

**⌀18-Schulter wie im Lüfterhalter.** Kollidiert an einem Loch mit einem
Gussmerkmal. ⌀16 ist das Maximum.

---

## Offene Punkte

1. **Welche Seite ist „links"?** `SIDE = -1` legt den Kanal auf die −X-Seite,
   das ist die Seite mit den OUT-Bolzen. `SIDE = +1` spiegelt die ganze Haube.
   Vor dem Druck am realen Einbau prüfen.
2. **Ist eine Stirnseite durch Kabel zugestellt?** Dann gehört der Lüfter mit
   `FAN_OFFSET` zur Kanalseite versetzt, damit der untere Weg mehr bekommt.
3. **Bauhöhe über den Stirnseiten** — die Haube ist 61 mm hoch. Passt das im
   Einbau?
4. **Distanzstückhöhe** 8, 10 oder 12 mm ist noch nicht entschieden; 10 mm ist
   der Entwurfswert, alle drei sind exportiert.
5. Der **92-mm-Lüfterhalter** für den Sunon GF92251B1-000U-AE9 ist fertig, aber
   nie auf `hardware` committet worden. Lars wollte beide Größen behalten.
   Das ReadMe auf `hardware` erwähnt bisher nur 80 mm.

---

## Skripte

```
python3 duct_concept.py
python3 fanmount.py 80
python3 fanmount.py 92
python3 detail.py
```

`duct_concept.py` erzeugt Haube und Distanzstücke als STEP und STL,
`fanmount.py` den Lüfterhalter in der als Argument übergebenen Größe,
`detail.py` die Schnittzeichnung des Montagepunkts.

Braucht CadQuery 2.8 (`pip install cadquery`), für `detail.py` matplotlib.

`duct_concept.py` prüft gegen das Herstellermodell, wenn die STEP-Datei
danebenliegt — `converter()` wendet sie um die Längsachse und schiebt das
Bohrbild zurück auf `HOLES`. Ohne die Datei fällt es auf einen Quader zurück,
der die Senkungen **nicht** hat; eine Freigängigkeitsprüfung meldet dann die
Zapfen fälschlich als Kollision.

Beim Wenden **drehen, nicht spiegeln** — eine Spiegelung ergibt das andere
Teil. Das Bohrbild liegt nicht mittig, die Drehung braucht deshalb einen
Versatz von 2 × Mittelwert der Z-Lochkoordinaten.

### Prüfungen, die vor jeder Freigabe laufen sollten

```python
import duct_concept as d, trimesh
h = d.hood()
len(h.val().Solids()) == 1                      # ein Körper
h.intersect(d.converter()).val().Volume() == 0  # gegen das echte Modell
h.intersect(d.spacers(10)).val().Volume() == 0
trimesh.load('print_hood.stl').is_watertight
```

Ein Volumen knapp über null bei den Boolean-Prüfungen heißt fast immer:
zwei Flächen liegen koplanar oder tangential aufeinander. Das erzeugt
Splitterhohlräume im Solid. Lösung ist ein bewusster Überstand von 0,02 mm,
kein Toleranzspiel.
