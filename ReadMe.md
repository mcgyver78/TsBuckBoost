# TsBuckBoost

Venus OS driver for the Victron Buck-Boost DC-DC converter — no VE.Direct needed.
Venus-OS-Treiber für den Victron Buck-Boost DC-DC-Wandler — ganz ohne VE.Direct.

**[English](#english) · [Deutsch](#deutsch)**

---

## English

Publishes a Victron Buck-Boost DC-DC converter (25 A / 50 A / 100 A) on the Venus OS
D-Bus as `com.victronenergy.alternator`. The converter then shows up like an Orion XS
in the GX display — including the overview page next to solar — in the VRM portal and
in Node-RED's Victron nodes — even though the
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
| `/DeviceOffReason` | 0x08 = remote connector, set while pin 1 disables the unit |
| `/ProductName`, `/Serial`, `/FirmwareVersion` | Device identification |

> **Note on the GX display:** the alternator device page shows neither an on/off
> switch nor an off reason — only the dcdc page has those, and dcdc does not appear
> on the overview. Pin 1 state is therefore published on D-Bus but not rendered by
> the GUI. Read it through MQTT, the Victron nodes in Node-RED, or directly:
>
> ```bash
> dbus -y com.victronenergy.alternator.tsbb_ttyUSB1 /DeviceOffReason GetValue
> ```

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

### Why alternator and not dcdc

Venus OS has a `com.victronenergy.dcdc` service class, and on paper it fits a
Buck-Boost perfectly. It does not work for the overview page, though:
`dbus-systemcalc-py` monitors solarcharger, battery, fuelcell, charger, temperature,
inverter, multi, acsystem, dcsystem, alternator and dcgenset — but not dcdc. The
overview tile is fed from `/Dc/Alternator/Power`, which is summed over alternator
services only, so a dcdc service appears in the device list and nowhere else.

Victron takes the same view internally. From `delegates/dvcc.py`:

```python
class Alternator(BaseCharger, Networkable):
    """ This also includes other DC/DC converters. """
```

DVCC will not try to control this device: it only writes to `/Link/ChargeVoltage`
and `/Link/ChargeCurrent`, and only when the service actually publishes them. This
driver does not — which is honest, because the converter cannot be controlled over
this interface.

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

### Troubleshooting

**The device does not appear in the GX device list.** Look at the log first:

```bash
tail -f /var/log/TsBuckBoost/current
```

`keine Antwort auf die Typabfrage` means something else is holding the port — see
below. `unbekannte Geraetekennung` means the port was found but a different device
answered; the driver stops on purpose rather than talking to it.

**Only one master per port.** The converter answers request by request, without
framing or checksums. If a second process reads the same port at the same time, both
sides receive shifted garbage: unknown device ids, wrong block lengths, ASCII text in
the middle of the data, or a block that looks like the previous one moved by a byte or
two. Before running any manual tool, stop the service and make sure it is gone:

```bash
svc -d /service/TsBuckBoost
sleep 3
pgrep -f dbus-tsbb.py        # must stay empty
```

Start it again afterwards with `svc -u /service/TsBuckBoost`, restart it with
`svc -t /service/TsBuckBoost`.

**`ttyUSB` numbers move around.** After a reboot or a re-plug, `ttyUSB1` may well be a
different device than yesterday. The driver therefore resolves its port through
`/dev/serial/by-id/` and verifies it with the protocol's type query. Manual scripts
should do the same:

```bash
PORT=$(/data/TsBuckBoost/find-port.sh); echo "$PORT"
```

**The current stays at zero.** That is usually correct: the driver reports current
only while status bit 0 is set, exactly like TSConfig. The converter starts with a
delay and only once the input voltage passes its switch-on threshold (setting 57,
13.3 V by default) — an alternator idling below that will not trigger it. If your
installation switches a fan through pin 1, that fan is the most reliable indicator of
when the converter is actually working.

**VRM shows the wrong device instance.** The instance is stored in
`/Settings/Devices/tsbuckboost/ClassAndVrmInstance` and defaults to `dcdc:40`. If it
collides with another device, change it there and restart the service.

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
Venus OS als `com.victronenergy.alternator` an. Damit erscheint der Wandler wie ein
Orion XS im GX-Display — auch in der grafischen Übersicht neben Solar —, im
VRM-Portal und in den Victron-Nodes von Node-RED, obwohl
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
| `/DeviceOffReason` | 0x08 = Remote connector, gesetzt solange Pin 1 sperrt |
| `/ProductName`, `/Serial`, `/FirmwareVersion` | Gerätekennung |

> **Hinweis zum GX-Display:** Die Alternator-Geräteseite zeigt weder einen
> Ein/Aus-Schalter noch einen Abschaltgrund — beides kennt nur die dcdc-Seite, und
> dcdc taucht dafür nicht in der Übersicht auf. Der Pin-1-Zustand liegt also auf dem
> D-Bus, wird von der Oberfläche aber nicht dargestellt. Auslesen über MQTT, die
> Victron-Nodes in Node-RED oder direkt:
>
> ```bash
> dbus -y com.victronenergy.alternator.tsbb_ttyUSB1 /DeviceOffReason GetValue
> ```

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

### Warum alternator und nicht dcdc

Venus OS kennt die Dienstklasse `com.victronenergy.dcdc`, und auf dem Papier passt
sie perfekt auf einen Buck-Boost. Für die grafische Übersicht taugt sie aber nicht:
`dbus-systemcalc-py` überwacht solarcharger, battery, fuelcell, charger, temperature,
inverter, multi, acsystem, dcsystem, alternator und dcgenset — dcdc steht nicht auf
der Liste. Die Kachel in der Übersicht speist sich aus `/Dc/Alternator/Power`, und
das wird ausschließlich über Alternator-Dienste summiert. Ein dcdc-Dienst erscheint
deshalb in der Geräteliste und sonst nirgends.

Victron sieht das intern genauso. Aus `delegates/dvcc.py`:

```python
class Alternator(BaseCharger, Networkable):
    """ This also includes other DC/DC converters. """
```

DVCC versucht nicht, dieses Gerät zu steuern: Geschrieben wird nur nach
`/Link/ChargeVoltage` und `/Link/ChargeCurrent`, und auch das nur, wenn der Dienst
diese Pfade veröffentlicht. Dieser Treiber tut es nicht — was ehrlich ist, denn über
diese Schnittstelle lässt sich der Wandler nicht steuern.

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

### Fehlersuche

**Das Gerät taucht nicht in der GX-Geräteliste auf.** Zuerst ins Log schauen:

```bash
tail -f /var/log/TsBuckBoost/current
```

`keine Antwort auf die Typabfrage` heißt, dass jemand anderes den Port hält — siehe
unten. `unbekannte Geraetekennung` heißt, dass der Port gefunden wurde, dort aber ein
fremdes Gerät antwortet; der Treiber bricht dann absichtlich ab, statt darauf
herumzureden.

**Immer nur ein Master auf dem Port.** Der Wandler antwortet Frage für Frage, ohne
Rahmen und ohne Prüfsumme. Liest ein zweiter Prozess gleichzeitig mit, bekommen beide
Seiten verschobenen Müll: unbekannte Gerätekennungen, falsche Blocklängen, ASCII-Text
mitten in den Daten oder ein Block, der wie der vorige aussieht, nur um ein, zwei
Bytes versetzt. Vor jedem manuellen Werkzeug also den Dienst stoppen und kontrollieren:

```bash
svc -d /service/TsBuckBoost
sleep 3
pgrep -f dbus-tsbb.py        # muss leer bleiben
```

Danach wieder starten mit `svc -u /service/TsBuckBoost`, neu starten mit
`svc -t /service/TsBuckBoost`.

**`ttyUSB`-Nummern wandern.** Nach einem Neustart oder Umstecken kann `ttyUSB1` ein
ganz anderes Gerät sein als gestern. Der Treiber löst seinen Port deshalb über
`/dev/serial/by-id/` auf und verifiziert ihn über die Typabfrage des Protokolls.
Manuelle Skripte sollten das genauso halten:

```bash
PORT=$(/data/TsBuckBoost/find-port.sh); echo "$PORT"
```

**Der Strom bleibt auf null.** Das ist meistens richtig so: Der Treiber meldet Strom
nur, solange Statusbit 0 gesetzt ist — genau wie TSConfig. Der Wandler startet
verzögert und erst, wenn die Eingangsspannung seine Einschaltschwelle übersteigt
(Einstellung 57, ab Werk 13,3 V). Eine Lichtmaschine, die im Standlauf darunter
bleibt, löst ihn nicht aus. Wer über Pin 1 einen Lüfter schaltet, hat mit dessen
Geräusch die zuverlässigste Anzeige dafür, wann der Wandler wirklich arbeitet.

**VRM zeigt die falsche Geräteinstanz.** Sie steht in
`/Settings/Devices/tsbuckboost/ClassAndVrmInstance` und ist mit `dcdc:40` vorbelegt.
Bei einer Kollision dort ändern und den Dienst neu starten.

### Geprüft mit

Buck-Boost 50 A (Kennung 113 / TS800C5) in einem 12 → 24 V Aufbau, gegen SmartShunt
und BMS als Referenz: Ausgangsspannung 26,89 V gegen 26,88 V, Ausgangsstrom 27,56 A
gegen 26,93 A am Shunt — die Differenz ist die Systemlast, die vor dem Shunt abgeht.

### Lizenz

MIT
