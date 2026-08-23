# TsBuckBoost

Venus OS driver for the Victron Buck-Boost DC-DC converter — no VE.Direct needed.
Venus-OS-Treiber für den Victron Buck-Boost DC-DC-Wandler — ganz ohne VE.Direct.

**[English](#english) · [Deutsch](#deutsch)**

---

## English

Publishes a Victron Buck-Boost DC-DC converter (25 A / 50 A / 100 A) on the Venus OS
D-Bus as `com.victronenergy.dcdc`. The converter then shows up like an Orion XS in
the GX display, in the VRM portal and in Node-RED's Victron nodes — even though the
device has neither VE.Direct nor Bluetooth.

The Buck-Boost is not a Victron design. It is an OEM product by
**top systems b.v.** (today TS Enovations), sold as the TS 400 / TS 800 / TS 1600
series. Out of the box it can only be configured with the Windows tool *TSConfig*.

### What the driver publishes

| D-Bus path | Content |
|---|---|
| `/Dc/0/Voltage` | Output voltage |
| `/Dc/0/Current` | Output current (sum of the three measuring channels) |
| `/Dc/0/Power` | Output power |
| `/Dc/In/V` | Input voltage |
| `/Dc/0/Temperature` | MOSFET temperature |
| `/State` | 3 = charging, 0 = off |
| `/Mode` | 1 = enabled, 4 = disabled through pin 1 (read-only) |
| `/ProductName`, `/Serial`, `/FirmwareVersion` | Device identification |

### Safety

The driver sends **read commands only** (`FE 11` and `FE D0`). Write commands are
deliberately not implemented: the converter accepts parameter changes *and firmware
updates* over the same interface, so a wrong address could alter charge parameters
or push the device into its bootloader. Keep using TSConfig for configuration.

### Installation

#### With SetupHelper (recommended)

Install [SetupHelper](https://github.com/kwindrem/SetupHelper), then in the GX menu
go to *Settings → Package manager → Inactive packages → new* and enter:

| Field | Value |
|---|---|
| Package name | `TsBuckBoost` |
| GitHub user | `mcgyver78` |
| GitHub branch or tag | `latest` |

Then *Proceed* → *Install*.

#### Manually

```bash
cd /data
git clone https://github.com/mcgyver78/TsBuckBoost.git
/data/TsBuckBoost/setup
```

### Requirements

- Venus OS with Python 3 and `pyserial` (both shipped with Venus OS)
- The converter connected to the GX device with a USB-A to USB-B cable

### Serial starter

Venus OS attaches a service to every newly detected `ttyUSB` and probes it for
VE.Direct and MK2. The bundled service releases the Buck-Boost port before starting
(`stop-tty.sh`). The port is located through `/dev/serial/by-id/*CP210*` and then
verified with the protocol's own type query — if a foreign device answers there, the
driver exits instead of talking to it.

### Protocol

Reconstructed from TSConfig v2.4.4 (VB.NET, not obfuscated). 9600 8N1, DTR and RTS
asserted, no checksum.

```
FE 11 <page> <addr> <len>   read
FE 02 <page> <addr> <val>   write (not implemented here)
FE D0                       live data block, 19 or 22 bytes
FE CF                       auxiliary block, 4 bytes
```

Inside the live block, big endian:

| Byte | Content |
|---|---|
| 0·1, 2·3, 4·5 | current channels 1–3, raw |
| 10·11 | output voltage, raw |
| 12·13 | input voltage, raw |
| 18, 19, 20 | temperatures (board, PCB, MOSFET), signed |
| 21 | status bits, see below |

Status byte 21:

| Bit | Meaning |
|---|---|
| 0 (0x01) | converter is converting — verified |
| 1 (0x02) | enabled, waiting — inferred |
| 3 (0x08) | run-on after switch-off — inferred |
| 5 (0x20) | disabled through the pin 1 input — verified |

`/Mode` mirrors bit 5: 1 = enabled, 4 = disabled. It is read-only — the converter
cannot be switched over this interface, only through the hardware input on pin 1.

Converting those raw values needs per-device calibration data, which the driver
reads from the converter at startup:

| Command | Content |
|---|---|
| `FE 11 1F F2 01` | device id (113 = TS800C5, 108 = TS800C3, …) |
| `FE 11 1F F5 01` | current sense chip: 1 = INA226, 2 = INA238 |
| `FE 11 1F E0 10` | bytes 0–2: current factors of the three channels, mA per count |
| `FE 11 1F 2A 40` | bytes 41–43: zero points of the three channels |

Resulting in:

```
V_in    = raw / 1024 · 2 / 0.0636
V_out   = raw · SpFactor            (0.00125 for INA226, 0.003125 for INA238)
I_out   = Σ max(0, (raw_k − zero_k) · factor_k)
```

### Verified against

Buck-Boost 50 A (id 113 / TS800C5) in a 12 → 24 V installation, checked against a
SmartShunt and a BMS: output voltage 26.89 V vs. 26.88 V, output current 27.56 A vs.
26.93 A at the shunt — the difference being the system load that is drawn ahead of
the shunt.

### License

MIT

---

## Deutsch

Meldet einen Victron Buck-Boost DC-DC-Wandler (25 A / 50 A / 100 A) auf dem D-Bus von
Venus OS als `com.victronenergy.dcdc` an. Damit erscheint der Wandler wie ein
Orion XS im GX-Display, im VRM-Portal und in den Victron-Nodes von Node-RED — obwohl
das Gerät weder VE.Direct noch Bluetooth besitzt.

Der Buck-Boost ist kein Victron-Eigenentwurf, sondern ein OEM-Gerät von
**top systems b.v.** (heute TS Enovations), Baureihe TS 400 / TS 800 / TS 1600.
Ab Werk lässt er sich ausschließlich mit der Windows-Software *TSConfig*
konfigurieren.

### Was der Treiber liefert

| D-Bus-Pfad | Inhalt |
|---|---|
| `/Dc/0/Voltage` | Ausgangsspannung |
| `/Dc/0/Current` | Ausgangsstrom (Summe der drei Messkanäle) |
| `/Dc/0/Power` | Ausgangsleistung |
| `/Dc/In/V` | Eingangsspannung |
| `/Dc/0/Temperature` | MOSFET-Temperatur |
| `/State` | 3 = lädt, 0 = aus |
| `/Mode` | 1 = freigegeben, 4 = über Pin 1 gesperrt (nur lesbar) |
| `/ProductName`, `/Serial`, `/FirmwareVersion` | Gerätekennung |

### Sicherheit

Der Treiber sendet **ausschließlich Lesekommandos** (`FE 11` und `FE D0`).
Schreibende Kommandos sind bewusst nicht implementiert: Der Wandler nimmt über
dieselbe Schnittstelle Parameteränderungen *und Firmware-Updates* entgegen, und eine
falsch getroffene Adresse könnte Ladeparameter verstellen oder das Gerät in den
Bootloader schicken. Konfiguriert wird weiterhin mit TSConfig.

### Installation

#### Mit SetupHelper (empfohlen)

[SetupHelper](https://github.com/kwindrem/SetupHelper) installieren, dann im GX-Menü
unter *Settings → Package manager → Inactive packages → new* eintragen:

| Feld | Wert |
|---|---|
| Package name | `TsBuckBoost` |
| GitHub user | `mcgyver78` |
| GitHub branch or tag | `latest` |

Anschließend *Proceed* → *Install*.

#### Manuell

```bash
cd /data
git clone https://github.com/mcgyver78/TsBuckBoost.git
/data/TsBuckBoost/setup
```

### Voraussetzungen

- Venus OS mit Python 3 und `pyserial` (beides in Venus OS enthalten)
- Der Wandler hängt per USB-A-auf-USB-B-Kabel am GX-Gerät

### Serial-Starter

Venus OS hängt an jedes neu erkannte `ttyUSB` automatisch einen Dienst und probiert
VE.Direct und MK2 durch. Der mitgelieferte Dienst gibt den Port des Buck-Boost vor
dem Start wieder frei (`stop-tty.sh`). Der Port wird über
`/dev/serial/by-id/*CP210*` gesucht und anschließend über die Typabfrage des
Protokolls verifiziert — antwortet dort ein fremdes Gerät, beendet sich der Treiber,
ohne zu stören.

### Protokoll

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
| 21 | Statusbits, siehe unten |

Statusbyte 21:

| Bit | Bedeutung |
|---|---|
| 0 (0x01) | Wandler wandelt — gemessen |
| 1 (0x02) | freigegeben, wartet — abgeleitet |
| 3 (0x08) | Nachlauf nach dem Abschalten — abgeleitet |
| 5 (0x20) | über den Eingang an Pin 1 gesperrt — gemessen |

`/Mode` bildet Bit 5 ab: 1 = freigegeben, 4 = gesperrt. Der Pfad ist nur lesbar —
der Wandler lässt sich über diese Schnittstelle nicht schalten, sondern nur über den
Hardware-Eingang an Pin 1.

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

### Geprüft mit

Buck-Boost 50 A (Kennung 113 / TS800C5) in einem 12 → 24 V Aufbau, gegen SmartShunt
und BMS als Referenz: Ausgangsspannung 26,89 V gegen 26,88 V, Ausgangsstrom 27,56 A
gegen 26,93 A am Shunt — die Differenz ist die Systemlast, die vor dem Shunt abgeht.

### Lizenz

MIT
