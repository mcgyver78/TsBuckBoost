# TsBuckBoost — Venus OS Treiber für den Victron Buck-Boost DC-DC Wandler

Meldet einen Victron Buck-Boost DC-DC Wandler (25 A / 50 A / 100 A) auf dem D-Bus
von Venus OS als `com.victronenergy.dcdc` an. Damit erscheint der Wandler wie ein
Orion XS im GX-Display, im VRM-Portal und in den Victron-Nodes von Node-RED —
obwohl das Gerät weder VE.Direct noch Bluetooth besitzt.

Der Wandler ist kein Victron-Eigenentwurf, sondern ein OEM-Gerät von
**top systems b.v.** (heute TS Enovations), Baureihe TS 400 / TS 800 / TS 1600.
Konfiguriert wird er ab Werk ausschließlich über die Windows-Software *TSConfig*.

## Was der Treiber liefert

| D-Bus-Pfad | Inhalt |
|---|---|
| `/Dc/0/Voltage` | Ausgangsspannung |
| `/Dc/0/Current` | Ausgangsstrom (Summe der drei Messkanäle) |
| `/Dc/0/Power` | Ausgangsleistung |
| `/Dc/In/V` | Eingangsspannung |
| `/Dc/0/Temperature` | MOSFET-Temperatur |
| `/State` | 3 = lädt, 0 = aus |
| `/ProductName`, `/Serial`, `/FirmwareVersion` | Gerätekennung |

## Sicherheit

Der Treiber sendet **ausschließlich Lesekommandos** (`FE 11` und `FE D0`).
Schreibende Kommandos sind bewusst nicht implementiert: Der Wandler nimmt über
dieselbe Schnittstelle Parameteränderungen und Firmware-Updates entgegen, und eine
falsch getroffene Adresse könnte Ladeparameter verstellen oder das Gerät in den
Bootloader schicken. Konfiguriert wird weiterhin mit TSConfig.

## Installation

### Mit SetupHelper (empfohlen)

[SetupHelper](https://github.com/kwindrem/SetupHelper) installieren, dann im
GX-Menü unter *Settings → Package manager → Inactive packages → new* eintragen:

| Feld | Wert |
|---|---|
| Package name | `TsBuckBoost` |
| GitHub user | `mcgyver78` |
| GitHub branch or tag | `latest` |

Anschließend *Proceed* → *Install*.

### Manuell

```bash
cd /data
git clone https://github.com/mcgyver78/TsBuckBoost.git
/data/TsBuckBoost/setup
```

## Voraussetzungen

- Venus OS mit Python 3 und `pyserial` (in Venus OS enthalten)
- Der Wandler hängt per USB-A-auf-USB-B-Kabel am GX-Gerät

## Serial-Starter

Venus OS hängt an jedes neu erkannte `ttyUSB` automatisch einen Dienst und probiert
VE.Direct und MK2 durch. Der mitgelieferte Dienst gibt den Port des Buck-Boost vor
dem Start wieder frei (`stop-tty.sh`). Der Port wird über
`/dev/serial/by-id/*CP210*` gesucht und anschließend über die Typabfrage des
Protokolls verifiziert — antwortet dort ein fremdes Gerät, beendet sich der Treiber,
ohne zu stören.

## Protokoll

Rekonstruiert aus TSConfig v2.4.4 (VB.NET, unobfuskiert). 9600 8N1, DTR und RTS
aktiv, keine Prüfsumme.

```
FE 11 <page> <addr> <len>   Lesen
FE 02 <page> <addr> <val>   Schreiben (hier nicht implementiert)
FE D0                       Live-Datenblock, 19 oder 22 Byte
FE CF                       Zusatzblock, 4 Byte
```

Im Live-Block, big endian:

| Byte | Inhalt |
|---|---|
| 0·1, 2·3, 4·5 | Strom Kanal 1–3, roh |
| 10·11 | Ausgangsspannung, roh |
| 12·13 | Eingangsspannung, roh |
| 18, 19, 20 | Temperaturen (Platine, PCB, MOSFET), vorzeichenbehaftet |
| 21 Bit 0 | Wandler aktiv |

Die Umrechnung braucht gerätespezifische Kalibrierwerte, die beim Start aus dem
Wandler gelesen werden:

| Kommando | Inhalt |
|---|---|
| `FE 11 1F F2 01` | Gerätekennung (113 = TS800C5, 108 = TS800C3, …) |
| `FE 11 1F F5 01` | Strommesschip: 1 = INA226, 2 = INA238 |
| `FE 11 1F E0 10` | Byte 0–2: Stromfaktoren der drei Kanäle, in mA je Zählschritt |
| `FE 11 1F 2A 40` | Byte 41–43: Nullpunkte der drei Kanäle |

Daraus:

```
V_ein   = roh / 1024 · 2 / 0,0636
V_aus   = roh · SpFactor            (0,00125 bei INA226, 0,003125 bei INA238)
I_aus   = Σ max(0, (roh_k − Nullpunkt_k) · Faktor_k)
```

## Geprüft mit

Buck-Boost 50 A (Kennung 113 / TS800C5) in einem 12 → 24 V Aufbau, gegen
SmartShunt und BMS als Referenz: Ausgangsspannung 26,89 V gegen 26,88 V,
Ausgangsstrom 27,56 A gegen 26,93 A am Shunt (die Differenz ist die Systemlast,
die vor dem Shunt abgeht).

## Lizenz

MIT
