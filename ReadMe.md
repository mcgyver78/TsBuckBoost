# TsBuckBoost

Venus OS driver for the Victron Buck-Boost DC-DC converter — no VE.Direct needed.
Venus-OS-Treiber für den Victron Buck-Boost DC-DC-Wandler — ganz ohne VE.Direct.

**[English](#english) · [Deutsch](#deutsch)**

---

## English

Publishes a Victron Buck-Boost DC-DC converter (25 A / 50 A / 100 A) on the Venus OS
D-Bus as `com.victronenergy.alternator`. The converter then shows up like an Orion XS
in the GX display — including the overview page next to solar — as well as in the VRM
portal and in Node-RED's Victron nodes, even though the device has neither VE.Direct
nor Bluetooth.

The Buck-Boost is not a Victron design. It is an OEM product by
**top systems b.v.** (today TS Enovations), sold as the TS 400 / TS 800 / TS 1600
series. Out of the box it can only be configured with the Windows tool *TSConfig*.

### What the driver publishes

| D-Bus path | Content |
|---|---|
| `/Dc/0/Voltage` | Output voltage |
| `/Dc/0/Current` | Output current (sum of the three measuring channels) |
| `/Dc/0/Power` | Output power |
| `/Dc/In/V`, `/Dc/1/Voltage` | Input voltage |
| `/Dc/0/Temperature` | Hottest MOSFET temperature |
| `/Temperature/Board` | Board temperature (byte 19) |
| `/Temperature/Mosfet1`, `/Temperature/Mosfet2` | Both MOSFET temperatures (bytes 18, 20) |
| `/Temperature/CanSensor` | CAN temperature sensor, invalid when no sensor is connected |
| `/Current/Channel1…3` | The three current measuring channels, individually |
| `/StatusByte`, `/Status/Converting`, `/Status/BlockedByPin1` | Raw status byte and the two decoded bits |
| `/State` | 3 = charging, 0 = off |
| `/History/EnergyOut` | Energy delivered, kWh, kept across restarts |
| `/Alarms/HighTemperature` | 0 = ok, 1 = warning at 75 °C, 2 = alarm at 85 °C (two readings in a row) |
| `/Mode` | 1 = enabled, 4 = disabled through pin 1 (read-only) |
| `/DeviceOffReason` | 0x08 = remote connector, set while pin 1 disables the unit |
| `/ProductName`, `/Serial`, `/FirmwareVersion` | Device identification |

> **Note on the GX display:** the alternator device page renders a fixed set of
> paths — output voltage, current, power, state and temperature. Everything beyond
> that (the individual temperatures, the current channels, the pin 1 state) is
> published on D-Bus but not drawn by the GUI, and there is no way for a driver to
> change that. Read those values through MQTT, the Victron nodes in Node-RED, or
> directly. The service name carries the tty the converter is on; the first
> command shows it:
>
> ```bash
> dbus -y | grep tsbb
> dbus -y com.victronenergy.alternator.tsbb_ttyUSB0 /DeviceOffReason GetValue
> ```

### Naming in Node-RED

The Victron nodes for Node-RED label every path from a fixed list of their own
(`services.json` in `node-red-contrib-victron`), written for real alternators. Two
labels therefore read oddly for a DC-DC converter, and a driver cannot change them:

| Path | Node-RED calls it | What it really is |
|---|---|---|
| `/Dc/0/Temperature` | *Battery temperature 0 (°C)* | hottest MOSFET of the converter |
| `/Dc/1/Voltage` | *Battery voltage 1 (V)* | input voltage, shown as *Aux voltage* on the GX |

Both values exist under a second, correctly named path — use those instead:

- input voltage: `/Dc/In/V`, listed as *Input voltage (before DC/DC converter)*
- temperatures: the four *Custom* input nodes in the flow under `extras/` read
  `/Temperature/Board`, `/Temperature/Mosfet1`, `/Temperature/Mosfet2` and
  `/Temperature/CanSensor` straight from the driver's service, correctly named and
  without any extra device. Alternatively switch on the separate temperature devices
  (below); they appear as their own Victron *Temperature* nodes named *Buck-Boost
  Board*, *Buck-Boost MOSFET 1*, *Buck-Boost MOSFET 2* and *Buck-Boost CAN sensor*.

`/Dc/0/Temperature` is kept because it is the only temperature the GX device page
draws — there it is labelled *Temperature*, which is accurate.

**Never choose the Buck-Boost as battery temperature.** Venus OS may offer it under
*Settings → DVCC → Temperature sensor*, because it publishes `/Dc/0/Temperature`.
Chosen there, 40–85 °C of MOSFET temperature would reach every charger as battery
temperature: the temperature compensation of lead batteries would lower the charge
voltage, and the low-temperature charge stop of a lithium battery would not trigger
in winter.

### Safety

The driver sends **read commands only** (`FE 11`, `FE D0` and `FE CF`). Write commands
are deliberately not implemented: the converter accepts parameter changes *and firmware
updates* over the same interface, so a wrong address could alter charge parameters
or push the device into its bootloader. Keep using TSConfig for configuration.

Every byte for the converter goes through one function in the driver that lets only
these three commands pass, and that sends nothing at all once another process has
changed the line settings of the port — at a foreign speed a read command would
reach the converter as different bytes.

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

Venus OS has no `git`. Fetch the branch as an archive, unpack it to `/data/TsBuckBoost`
and run the setup script — which still needs SetupHelper installed, because it uses
SetupHelper's helper resources for the install/uninstall logic:

```bash
cd /data
wget -O tsbb.tgz https://github.com/mcgyver78/TsBuckBoost/archive/refs/heads/latest.tar.gz
tar xzf tsbb.tgz && rm tsbb.tgz
mv TsBuckBoost-latest TsBuckBoost
/data/TsBuckBoost/setup
```

This is for a first installation. If `/data/TsBuckBoost` already exists, `mv` moves the
new files into it and the old driver keeps running — update through the package
manager instead, or remove the old directory first (`svc -d /service/TsBuckBoost`,
then `rm -rf /data/TsBuckBoost`).

### Requirements

- Venus OS with Python 3 and `pyserial` (both shipped with Venus OS)
- The converter connected to the GX device with a USB-A to USB-B cable
- A converter that answers the live query with the 22-byte block: every current
  Victron Buck-Boost (25 A = TS4003, 50 A = TS800C5, 100 A = TS16002) and the
  top systems TS 100, TS 1600, TS 800C2/C3 and TSEV1000. The older TS 200/400/800/800C
  use a 19-byte block with a different layout; the driver recognises them, logs
  `model not supported` and leaves the port alone rather than publishing wrong numbers.
- One Buck-Boost per GX device. Other CP210x-based USB devices may be present: on its
  first start the driver asks the CP210x ports for the converter id, leaves the others
  alone and remembers its port; after that it only asks that one (see Serial starter).

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

### Energy counter and temperature alarm

The GX device page for an alternator has an **Alarms** and a **History** submenu.
Both are filled by this driver.

`/History/EnergyOut` is integrated from output power while the converter is
actually converting, and stored in the Venus settings every five minutes and
whenever the driver stops or restarts, so the counter survives restarts and firmware
updates. VRM plots it as well. The protocol has no checksum, and a garbled block
decodes into thousands of volts and amps; a reading that cannot be real is discarded
instead of counted. A value written to `EnergyOut` from outside — to reset the
counter, say — is taken over.

`/Alarms/HighTemperature` watches the hotter of the two MOSFET sensors: warning at
75 °C, alarm at 85 °C, released again 5 K below with hysteresis. A level is entered
after two readings in a row, so a single garbled reading raises no alarm, and it
survives a restart of the driver. 85 °C is where the converter starts reducing
current on its own, so the alarm fires before the device throttles rather than
after. Voltage alarms are deliberately not published — sensible
thresholds depend on the battery chemistry, and wrong ones only produce noise in VRM.

### Optional: temperatures as separate devices

The alternator device page renders exactly one temperature row. If you want to see
the individual sensors in the GX display, the driver can register them as proper
Venus temperature devices — with their own name, history in VRM and alarm settings.
This is **off by default**, because it adds entries to the device list.

> The individual temperatures are **always** published, on the driver's own service
> under `/Temperature/Board`, `/Temperature/Mosfet1`, `/Temperature/Mosfet2` and
> `/Temperature/CanSensor`. The switch below only decides whether Venus additionally
> lists them as devices of their own. So if you read the values in Node-RED or over
> MQTT anyway, leave it off and keep the GX temperature page tidy — the flow in
> `extras/` contains ready-made input nodes for exactly that.

```bash
# on
dbus -y com.victronenergy.settings \
     /Settings/Devices/tsbuckboost/SeparateTempSensors SetValue 1
svc -t /service/start-gui

# off
dbus -y com.victronenergy.settings \
     /Settings/Devices/tsbuckboost/SeparateTempSensors SetValue 0
svc -t /service/start-gui
```

The driver restarts itself when the setting changes (v1.21 and later). The GUI has to
be restarted as well, or the device list keeps entries of devices that went away; on
older Venus OS releases the GUI service is `/service/gui`.

You then get *Buck-Boost Board*, *Buck-Boost MOSFET 1* and *Buck-Boost MOSFET 2*,
plus *Buck-Boost CAN sensor* as soon as a TS Temp sensor answers — the driver skips
that one while the converter reports “no signal”. The devices take their VRM
instances from `/Settings/Devices/tsbuckboost_board/ClassAndVrmInstance` and its
siblings `_mosfet1`, `_mosfet2` and `_cansensor`, preset to 41 to 44.

The switch lives in the settings tree, not in a GX menu, so it survives package
updates. Editing the driver file instead would not: the next install replaces it.

**Without the console.** `extras/nodered-separate-temp-sensors.json` is a small
Node-RED flow that does the same thing: import it through the Node-RED menu
(*Import → clipboard*), then click *manual ON* or *manual OFF*. The `exec` node writes
the setting on the GX device; the driver restarts itself, and the flow restarts the
GX user interface so that the device list is redrawn — the display goes black for a
few seconds, nothing else on the system is affected. The debug node reports back
whether it worked, with the value of the setting as read back.

The flow reads the setting before writing and only acts on a real change. One
command runs at a time; a tap while one is running only replaces the pending wish,
which runs afterwards. The switch always shows the setting as read back from the GX —
after every command, when the flow starts and every ten minutes. Its report after a
deploy is answered by reading the setting, never by writing it.

If you had been reading the temperatures through the separate temperature devices in
Node-RED, switching them off takes those nodes' source away. Use the input nodes
described next instead; they keep working either way.

The flow also carries four input nodes that read the temperatures from the driver's
own service, independent of the switch. They are preset to device instance 40, the
driver's default; if yours differs, open a node and pick the converter from the list.
Check with:

```bash
dbus -y com.victronenergy.settings \
     /Settings/Devices/tsbuckboost/ClassAndVrmInstance GetValue
```

The flow also ships a `victron-virtual-switch` named *Buck-Boost additional sensors*,
which puts a real switch on the GX display — that is the point of the flow for anyone
who never opens a console. The trigger is kept separate from the action, so anything
else can drive it too: the two inject nodes, a dashboard switch, or your own logic.
The action understands `1`/`0`, `true`/`false`, `on`/`off` — as numbers, booleans or
strings in any case. Anything else is ignored with a warning rather than guessed,
because a guess would restart the driver and the display. The setting as read back is
fed into the virtual switch, so its position on the GX display matches the setting —
after the inject nodes at once, after a change from the console within ten minutes.

Requirements for the flow: the TsBuckBoost driver v1.21 or later (it restarts itself
when the setting changes), the Victron Node-RED nodes (for the virtual switch and the
four input nodes) and a Node-RED instance allowed to run commands on the GX device.
The GUI restart uses `start-gui`, or `gui` on older Venus OS releases. If it fails —
because Node-RED may not control services, for instance — the debug node says so;
the setting is written and the driver restarted all the same.

### Serial starter

Venus OS attaches a service to every newly detected `ttyUSB` and probes it for
VE.Direct and MK2. The driver remembers the by-id port of its converter in
`/Settings/Devices/tsbuckboost/Port`. While that port exists, it is the only one
asked: it is taken away from serial-starter (`stop-tty.sh`) and then asked for the
converter id. If it stays silent, the converter is probably switched off, and the
driver asks again — after 10 s at first, then with growing pauses of up to five
minutes; a newly plugged port ends the wait. Only on the first start, or when that
port is gone, are all `/dev/serial/by-id/*CP210*` ports asked.

A port is asked with care. The line has to stay quiet before the question — a device
that talks on its own, like a GPS, gets nothing written into it —, the answer has to
be exactly one byte, twice the same, and a type the driver can decode. Only then is
the port taken away from serial-starter; a foreign CP210x device keeps its own
service. Opening a port sets its line for every process that has it open, so the
settings found on it are put back after the question.

A port that another driver has claimed is skipped while that driver holds it open.
serial-starter keeps a node under `/dev/serial-starter` for every tty it still
manages, and a driver claiming a port removes it — this driver as well, so a port
without a node only counts as taken while another process really has it open (read
from `/proc`). A driver that is restarting at that very moment is not protected.

The port is opened exclusively. pyserial implements that as an advisory lock: it
keeps out other drivers that lock as well, while probes and drivers that do not lock
get in all the same. So before every question the driver checks that the line is
still set to 9600 8N1; if another process has changed it, nothing is sent and the
driver restarts, which opens the port afresh. After two polls without an answer the
port is taken back from serial-starter once: another driver looking for its own
hardware may have handed it back at any moment, and one call is cheaper than the
service restart that follows five failed polls.

### Protocol

Reconstructed from TSConfig v2.4.4 (VB.NET, not obfuscated). 9600 8N1, DTR and RTS
asserted, no checksum.

```
FE 11 <page> <addr> <len>   read
FE 02 <page> <addr> <val>   write (not implemented here)
FE D0                       live data block, 22 bytes (19 on old types, not decoded)
FE CF                       auxiliary block, 4 bytes
```

Inside the live block, big endian:

| Byte | Content |
|---|---|
| 0·1, 2·3, 4·5 | current channels 1–3, raw |
| 10·11 | output voltage, raw |
| 12·13 | input voltage, raw |
| 18, 20 | MOSFET temperatures, signed |
| 19 | board temperature, signed |
| 21 | status bits, see below |

The auxiliary block `FE CF` carries the CAN temperature sensor in its first byte,
also signed. A value of **−101 means “no signal”** — TSConfig writes exactly that
into the field and colours it yellow. The driver publishes the path as invalid in
that case instead of showing a nonsense reading.

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
V_in    = raw / 1024 · 2 / 0.0636      (0.13 instead of 0.0636 on the TSEV1000)
V_out   = raw · SpFactor               TS800C3/C5, TS16002, TSEV1000
                                       (0.00125 for INA226, 0.003125 for INA238)
V_out   = raw / 1024 · 2 / 0.0636      all other types
I_out   = Σ max(0, (raw_k − zero_k) · factor_k)   while status bit 0 is set
```

### Troubleshooting

**The device does not appear in the GX device list.** Look at the log first:

```bash
tail -f /var/log/TsBuckBoost/current
```

multilog starts a new file every 25 kB; if `tail -f` stops showing new lines, start it
again.

`no converter answers, skipping` means the port was found but nothing with a known id
answered — usually something else is holding the port, see below. `does not answer`
together with `no converter found (round n), next try in … s` means the remembered
port is there but silent: the converter is switched off or not powered, and the
driver keeps asking with growing pauses. `belongs to another driver, skipping` means
another process holds that port open. `model not supported, port left alone` means
an old short-block converter answered (see Requirements). `short answer to the
calibration query` means the start-up read was disturbed; the driver restarts rather
than running with unknown zero points, and normally succeeds on the next attempt.
`implausible block` means a reading that cannot be real was discarded; many of them
point to foreign traffic on the line. `line settings … changed underneath us` means
another process reconfigured the port; the driver restarts and sends nothing until
it has reopened it. `polls without an answer - restarting` means the port went dead,
for instance after a USB re-enumeration; the restart reopens it.

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

Start it again afterwards with `svc -u /service/TsBuckBoost` — the service stays down
until you do, also when the session breaks off in between. Restart it with
`svc -t /service/TsBuckBoost`.

**`ttyUSB` numbers move around.** After a reboot or a re-plug, `ttyUSB1` may well be a
different device than yesterday. The driver therefore resolves its port through
`/dev/serial/by-id/` and verifies it with the protocol's type query. To see the
CP210x ports — the driver skips those another driver holds open, and after its first
start it only asks the one it remembered:

```bash
/data/TsBuckBoost/find-port.sh
```

For a manual test on one specific port, pass it as an argument — then the driver
neither probes nor touches serial-starter, and does not remember the port:

```bash
python3 /data/TsBuckBoost/dbus-tsbb.py /dev/serial/by-id/usb-Silicon_Labs_CP2102N_…-port0
```

**The current stays at zero.** That is usually correct: the driver reports current
only while status bit 0 is set, exactly like TSConfig. The converter starts with a
delay and only once the input voltage passes its switch-on threshold (setting 57,
13.3 V by default) — an alternator idling below that will not trigger it. If your
installation switches a fan through pin 1, that fan is the most reliable indicator of
when the converter is actually working.

**VRM shows the wrong device instance.** The instance is stored in
`/Settings/Devices/tsbuckboost/ClassAndVrmInstance` and defaults to `alternator:40`. If it
collides with another device, change it there and restart the service. The separate
temperature devices keep theirs in `/Settings/Devices/tsbuckboost_board/ClassAndVrmInstance`
and its siblings.

### Fan mount

A 3D-printable mount for an 80 mm fan on the Buck-Boost 50 A, as STEP and STL, lives on
the separate [`hardware`](https://github.com/mcgyver78/TsBuckBoost/tree/hardware) branch
— it is kept out of the package so
SetupHelper does not copy it onto every GX device. The converter derates on temperature,
so a slow-running fan keeps the charge current up in a warm compartment, which is also
what makes the temperature readings above worth watching. Not required for the driver.

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
| `/Dc/In/V`, `/Dc/1/Voltage` | Eingangsspannung |
| `/Dc/0/Temperature` | heißeste MOSFET-Temperatur |
| `/Temperature/Board` | Platinentemperatur (Byte 19) |
| `/Temperature/Mosfet1`, `/Temperature/Mosfet2` | beide MOSFET-Temperaturen (Byte 18, 20) |
| `/Temperature/CanSensor` | CAN-Temperatursensor, ungültig wenn keiner angeschlossen ist |
| `/Current/Channel1…3` | die drei Strommesskanäle einzeln |
| `/StatusByte`, `/Status/Converting`, `/Status/BlockedByPin1` | rohes Statusbyte und die beiden dekodierten Bits |
| `/State` | 3 = lädt, 0 = aus |
| `/History/EnergyOut` | gelieferte Energie in kWh, überlebt Neustarts |
| `/Alarms/HighTemperature` | 0 = ok, 1 = Warnung ab 75 °C, 2 = Alarm ab 85 °C (zwei Messungen in Folge) |
| `/Mode` | 1 = freigegeben, 4 = über Pin 1 gesperrt (nur lesbar) |
| `/DeviceOffReason` | 0x08 = Remote connector, gesetzt solange Pin 1 sperrt |
| `/ProductName`, `/Serial`, `/FirmwareVersion` | Gerätekennung |

> **Hinweis zum GX-Display:** Die Alternator-Geräteseite zeichnet einen festen Satz
> von Pfaden — Ausgangsspannung, -strom, -leistung, Zustand und eine Temperatur.
> Alles darüber hinaus (die einzelnen Temperaturen, die Strommesskanäle, der
> Pin-1-Zustand) liegt auf dem D-Bus, wird von der Oberfläche aber nicht angezeigt,
> und ein Treiber kann daran nichts ändern. Auslesen über MQTT, die Victron-Nodes
> in Node-RED oder direkt. Der Dienstname trägt das tty, an dem der Wandler hängt;
> der erste Befehl zeigt ihn:
>
> ```bash
> dbus -y | grep tsbb
> dbus -y com.victronenergy.alternator.tsbb_ttyUSB0 /DeviceOffReason GetValue
> ```

### Benennung in Node-RED

Die Victron-Nodes für Node-RED beschriften jeden Pfad aus einer eigenen, festen
Liste (`services.json` in `node-red-contrib-victron`), geschrieben für echte
Lichtmaschinen. Zwei Beschriftungen lesen sich für einen DC-DC-Wandler deshalb
schief, und ein Treiber kann daran nichts ändern:

| Pfad | Node-RED nennt ihn | Was es wirklich ist |
|---|---|---|
| `/Dc/0/Temperature` | *Battery temperature 0 (°C)* | heißester MOSFET des Wandlers |
| `/Dc/1/Voltage` | *Battery voltage 1 (V)* | Eingangsspannung, im GX als *Aux voltage* |

Beide Werte gibt es unter einem zweiten, korrekt benannten Pfad — nimm die:

- Eingangsspannung: `/Dc/In/V`, in der Liste als *Input voltage (before DC/DC
  converter)*
- Temperaturen: die vier *Custom*-Eingangs-Nodes im Flow unter `extras/` lesen
  `/Temperature/Board`, `/Temperature/Mosfet1`, `/Temperature/Mosfet2` und
  `/Temperature/CanSensor` direkt aus dem Dienst des Treibers — korrekt benannt und
  ohne zusätzliches Gerät. Alternativ die separaten Temperaturgeräte einschalten
  (siehe unten); sie erscheinen als eigene Victron-*Temperature*-Nodes namens
  *Buck-Boost Board*, *Buck-Boost MOSFET 1*, *Buck-Boost MOSFET 2* und *Buck-Boost
  CAN sensor*.

`/Dc/0/Temperature` bleibt trotzdem bestehen, weil es die einzige Temperatur ist,
die die GX-Geräteseite zeichnet — dort steht *Temperature*, und das stimmt.

**Den Buck-Boost nie als Batterietemperatur wählen.** Venus OS bietet ihn unter
*Settings → DVCC → Temperature sensor* womöglich an, weil er `/Dc/0/Temperature`
veröffentlicht. Dort gewählt, ginge 40–85 °C MOSFET-Temperatur als Batterietemperatur
an alle Ladegeräte: Die Temperaturkompensation von Bleibatterien würde die
Ladespannung senken, und die Kälte-Ladesperre einer Lithiumbatterie griffe im Winter
nicht.

### Sicherheit

Der Treiber sendet **ausschließlich Lesekommandos** (`FE 11`, `FE D0` und `FE CF`).
Schreibende Kommandos sind bewusst nicht implementiert: Der Wandler nimmt über
dieselbe Schnittstelle Parameteränderungen *und Firmware-Updates* entgegen, und eine
falsch getroffene Adresse könnte Ladeparameter verstellen oder das Gerät in den
Bootloader schicken. Konfiguriert wird weiterhin mit TSConfig.

Jedes Byte an den Wandler geht durch eine einzige Funktion im Treiber, die nur diese
drei Kommandos durchlässt und gar nichts sendet, sobald ein anderer Prozess die
Leitungseinstellung des Ports verändert hat — mit fremder Baudrate käme ein
Lesekommando beim Wandler als andere Bytes an.

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

Venus OS hat kein `git`. Den Branch als Archiv holen, nach `/data/TsBuckBoost`
entpacken und das Setup-Skript starten — das braucht trotzdem einen installierten
SetupHelper, weil es dessen Hilfsroutinen für Installation und Deinstallation nutzt:

```bash
cd /data
wget -O tsbb.tgz https://github.com/mcgyver78/TsBuckBoost/archive/refs/heads/latest.tar.gz
tar xzf tsbb.tgz && rm tsbb.tgz
mv TsBuckBoost-latest TsBuckBoost
/data/TsBuckBoost/setup
```

Das gilt für die Erstinstallation. Gibt es `/data/TsBuckBoost` schon, schiebt `mv` die
neuen Dateien hinein, und der alte Treiber läuft weiter — Updates also über den
Package Manager, oder vorher das alte Verzeichnis entfernen (`svc -d
/service/TsBuckBoost`, dann `rm -rf /data/TsBuckBoost`).

### Voraussetzungen

- Venus OS mit Python 3 und `pyserial` (beides in Venus OS enthalten)
- Der Wandler hängt per USB-A-auf-USB-B-Kabel am GX-Gerät
- Ein Wandler, der die Live-Abfrage mit dem 22-Byte-Block beantwortet: jeder aktuelle
  Victron Buck-Boost (25 A = TS4003, 50 A = TS800C5, 100 A = TS16002) sowie die
  top-systems-Typen TS 100, TS 1600, TS 800C2/C3 und TSEV1000. Die älteren
  TS 200/400/800/800C liefern einen 19-Byte-Block mit anderem Aufbau; der Treiber
  erkennt sie, meldet `model not supported` und lässt den Port in Ruhe, statt falsche
  Zahlen zu veröffentlichen.
- Ein Buck-Boost je GX-Gerät. Andere USB-Geräte mit CP210x-Chip dürfen daneben
  hängen: Beim ersten Start fragt der Treiber die CP210x-Ports nach der Gerätekennung,
  lässt die anderen in Ruhe und merkt sich seinen Port; danach fragt er nur noch
  diesen (siehe Serial-Starter).

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

### Energiezähler und Temperaturalarm

Die GX-Geräteseite eines Alternators hat die Unterseiten **Alarms** und **History**.
Beide füllt dieser Treiber.

`/History/EnergyOut` wird aus der Ausgangsleistung integriert, solange der Wandler
tatsächlich wandelt, und alle fünf Minuten sowie bei jedem Stopp oder Neustart des
Treibers in den Venus-Settings gesichert — der Zähler überlebt damit Neustarts und
Firmware-Updates. VRM zeichnet ihn ebenfalls mit. Das Protokoll hat keine Prüfsumme,
und ein verstümmelter Block ergibt Tausende Volt und Ampere; ein Messwert, der nicht
echt sein kann, wird verworfen statt gezählt. Wird `EnergyOut` von außen gesetzt —
etwa um den Zähler zurückzusetzen —, übernimmt der Treiber den Wert.

`/Alarms/HighTemperature` beobachtet den höheren der beiden MOSFET-Sensoren: Warnung
ab 75 °C, Alarm ab 85 °C, Rückfall mit 5 K Hysterese. Eine Stufe gilt erst nach zwei
Messungen in Folge, ein einzelner verstümmelter Messwert löst also keinen Alarm aus,
und sie übersteht einen Neustart des Treibers. Bei 85 °C beginnt der Wandler selbst,
den Strom zu begrenzen — der Alarm kommt also, bevor das Gerät abregelt, nicht
danach. Spannungsalarme gibt es bewusst nicht: Sinnvolle Schwellen hängen an der
Batteriechemie, und falsch gesetzte erzeugen nur Lärm im VRM.

### Optional: Temperaturen als eigene Geräte

Die Alternator-Geräteseite zeichnet genau eine Temperaturzeile. Wer die einzelnen
Sensoren im GX-Display sehen will, kann sie vom Treiber als vollwertige
Venus-Temperaturgeräte anmelden lassen — mit eigenem Namen, Verlauf in VRM und
Alarmschwellen. Standardmäßig ist das **aus**, weil es die Geräteliste verlängert.

> Die einzelnen Temperaturen liegen **immer** auf dem D-Bus, im Dienst des Treibers
> selbst unter `/Temperature/Board`, `/Temperature/Mosfet1`, `/Temperature/Mosfet2`
> und `/Temperature/CanSensor`. Der Schalter unten entscheidet nur, ob Venus sie
> zusätzlich als eigene Geräte führt. Wer die Werte ohnehin in Node-RED oder über
> MQTT liest, lässt ihn also aus und hält die Temperaturseite im GX übersichtlich —
> im Flow unter `extras/` liegen fertige Eingangs-Nodes dafür.

```bash
# ein
dbus -y com.victronenergy.settings \
     /Settings/Devices/tsbuckboost/SeparateTempSensors SetValue 1
svc -t /service/start-gui

# aus
dbus -y com.victronenergy.settings \
     /Settings/Devices/tsbuckboost/SeparateTempSensors SetValue 0
svc -t /service/start-gui
```

Der Treiber startet sich selbst neu, wenn sich die Einstellung ändert (ab v1.21). Die
GUI muss zusätzlich neu starten, sonst behält die Geräteliste die Einträge
verschwundener Geräte; auf älteren Venus-Versionen heißt ihr Dienst `/service/gui`.

Dann erscheinen *Buck-Boost Board*, *Buck-Boost MOSFET 1* und *Buck-Boost MOSFET 2*,
dazu *Buck-Boost CAN sensor*, sobald ein TS-Temp-Sensor antwortet — solange der
Wandler „no signal“ meldet, legt der Treiber dieses Gerät nicht an. Ihre
VRM-Instanzen stehen in `/Settings/Devices/tsbuckboost_board/ClassAndVrmInstance` und
den Geschwistern `_mosfet1`, `_mosfet2` und `_cansensor`, vorbelegt mit 41 bis 44.

Der Schalter liegt im Settings-Baum, nicht in einem GX-Menü, und überlebt damit
Paket-Updates. Eine Änderung in der Treiberdatei täte das nicht: Die nächste
Installation ersetzt sie.

**Ohne Konsole.** `extras/nodered-separate-temp-sensors.json` ist ein kleiner
Node-RED-Flow, der dasselbe erledigt: über das Node-RED-Menü importieren
(*Import → Zwischenablage*), dann auf *manual ON* oder *manual OFF* klicken. Der
`exec`-Node schreibt die Einstellung auf dem GX-Gerät; der Treiber startet sich selbst
neu, und der Flow startet die GX-Oberfläche neu, damit die Geräteliste neu gezeichnet
wird — das Display ist dabei ein paar Sekunden schwarz, der Rest des Systems läuft
ungestört weiter. Der Debug-Node meldet zurück, ob es geklappt hat, mit dem
zurückgelesenen Wert der Einstellung.

Der Flow liest die Einstellung vor dem Schreiben und wird nur bei einer echten
Änderung aktiv. Es läuft immer nur ein Befehl; ein Tipp während eines laufenden
Befehls ersetzt nur den wartenden Wunsch, der danach ausgeführt wird. Der Schalter
zeigt immer die vom GX zurückgelesene Einstellung — nach jedem Befehl, beim Start des
Flows und alle zehn Minuten. Seine Meldung nach einem Deploy wird mit Lesen
beantwortet, nie mit Schreiben.

Wer die Temperaturen in Node-RED bisher über die separaten Temperaturgeräte gelesen
hat: beim Abschalten verlieren diese Nodes ihre Quelle. Dafür sind die folgenden
Eingangs-Nodes da, die unabhängig davon weiterlaufen.

Im Flow liegen außerdem vier Eingangs-Nodes, die die Temperaturen direkt aus dem
Dienst des Treibers lesen — unabhängig vom Schalter. Sie sind auf Geräteinstanz 40
voreingestellt, den Standardwert des Treibers; weicht deine ab, öffne einen Node und
wähle den Wandler aus der Liste. Nachsehen mit:

```bash
dbus -y com.victronenergy.settings \
     /Settings/Devices/tsbuckboost/ClassAndVrmInstance GetValue
```

Im Flow steckt außerdem ein `victron-virtual-switch` namens *Buck-Boost additional
sensors*, der einen echten Schalter auf dem GX-Display anlegt — dafür ist der Flow
eigentlich da: für alle, die keine Konsole öffnen wollen. Auslöser und Aktion sind
bewusst getrennt, damit auch anderes davorhängen kann: die beiden Inject-Nodes, ein
Dashboard-Element oder eigene Logik. Die Aktion versteht `1`/`0`, `true`/`false` und
`on`/`off` — als Zahl, Boolean oder Zeichenkette in beliebiger Schreibweise. Alles
andere wird mit einer Warnung ignoriert statt geraten, denn ein Ratefehler würde
Treiber und Display neu starten. Die zurückgelesene Einstellung wird in den virtuellen
Schalter gespielt, damit seine Stellung auf dem GX-Display der Einstellung entspricht —
nach den Inject-Nodes sofort, nach einer Änderung über die Konsole binnen zehn
Minuten.

Voraussetzungen für den Flow: der TsBuckBoost-Treiber ab v1.21 (er startet sich bei
einer Änderung der Einstellung selbst neu), die Victron-Nodes für Node-RED (für den
virtuellen Schalter und die vier Eingangs-Nodes) und eine Node-RED-Instanz, die Befehle
auf dem GX-Gerät ausführen darf. Der GUI-Neustart nimmt `start-gui`, auf älteren
Venus-Versionen `gui`. Scheitert er — etwa weil Node-RED keine Dienste steuern darf —,
meldet der Debug-Node das; die Einstellung ist trotzdem geschrieben und der Treiber
neu gestartet.

Beschriftungen und Meldungen im Flow sind bewusst englisch, passend zum Rest des
Pakets und zur Venus-Oberfläche.

### Serial-Starter

Venus OS hängt an jedes neu erkannte `ttyUSB` automatisch einen Dienst und probiert
VE.Direct und MK2 durch. Der Treiber merkt sich den by-id-Port seines Wandlers in
`/Settings/Devices/tsbuckboost/Port`. Solange dieser Port existiert, fragt er nur ihn:
Er wird dem serial-starter entzogen (`stop-tty.sh`) und dann nach der Gerätekennung
gefragt. Bleibt er stumm, ist der Wandler vermutlich aus, und der Treiber fragt erneut
— zuerst nach 10 s, dann mit wachsenden Pausen bis fünf Minuten; ein neu
eingesteckter Port beendet die Wartezeit. Nur beim ersten Start, oder wenn dieser Port
fehlt, fragt er alle `/dev/serial/by-id/*CP210*`-Ports.

Gefragt wird mit Vorsicht. Vor der Frage muss die Leitung still sein — ein Gerät, das
von sich aus sendet, etwa ein GPS, bekommt nichts hineingeschrieben —, die Antwort
muss genau ein Byte sein, zweimal dasselbe, und ein Typ, den der Treiber dekodieren
kann. Erst dann wird der Port dem serial-starter entzogen; ein fremdes CP210x-Gerät
behält seinen eigenen Dienst. Das Öffnen eines Ports stellt die Leitung für jeden
Prozess um, der ihn offen hat; die vorgefundene Einstellung wird nach der Frage
deshalb wiederhergestellt.

Einen Port, den ein anderer Treiber beansprucht hat, überspringt er, solange dieser
Treiber ihn offen hält. Der serial-starter führt unter `/dev/serial-starter` für jedes
tty, das er noch verwaltet, einen Eintrag; wer einen Port übernimmt, entfernt ihn —
auch dieser Treiber. Ein Port ohne Eintrag gilt deshalb nur als belegt, solange ein
anderer Prozess ihn nachweislich offen hat (gelesen aus `/proc`). Ein Treiber, der
gerade in diesem Moment neu startet, ist nicht geschützt.

Der Port wird exklusiv geöffnet. pyserial setzt das als beratende Sperre um: Sie hält
andere Treiber fern, die ebenfalls sperren; Probe-Dienste und Treiber ohne Sperre
kommen trotzdem hinein. Vor jeder Frage prüft der Treiber deshalb, dass die Leitung
noch auf 9600 8N1 steht; hat ein anderer Prozess sie verstellt, sendet er nichts und
startet neu, was den Port frisch öffnet. Nach zwei Abfragen ohne Antwort holt er den
Port einmal zurück: Ein anderer Treiber auf der Suche nach seiner eigenen Hardware
kann ihn jederzeit an den serial-starter zurückgegeben haben, und ein Aufruf ist
billiger als der Dienstneustart nach fünf Fehlversuchen.

### Protokoll

Rekonstruiert aus TSConfig v2.4.4 (VB.NET, unobfuskiert). 9600 8N1, DTR und RTS
aktiv, keine Prüfsumme.

```
FE 11 <page> <addr> <len>   Lesen
FE 02 <page> <addr> <val>   Schreiben (hier nicht implementiert)
FE D0                       Live-Datenblock, 22 Byte (19 bei alten Typen, nicht dekodiert)
FE CF                       Zusatzblock, 4 Byte
```

Im Live-Block, big endian:

| Byte | Inhalt |
|---|---|
| 0·1, 2·3, 4·5 | Strom Kanal 1–3, roh |
| 10·11 | Ausgangsspannung, roh |
| 12·13 | Eingangsspannung, roh |
| 18, 20 | MOSFET-Temperaturen, vorzeichenbehaftet |
| 19 | Platinentemperatur, vorzeichenbehaftet |
| 21 | Statusbits, siehe unten |

Der Zusatzblock `FE CF` trägt im ersten Byte den CAN-Temperatursensor, ebenfalls
vorzeichenbehaftet. Der Wert **−101 bedeutet „no signal“** — TSConfig schreibt genau
das ins Feld und färbt es gelb. Der Treiber meldet den Pfad dann als ungültig,
statt einen Unsinnswert anzuzeigen.

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
V_ein   = roh / 1024 · 2 / 0,0636      (0,13 statt 0,0636 beim TSEV1000)
V_aus   = roh · SpFactor               TS800C3/C5, TS16002, TSEV1000
                                       (0,00125 bei INA226, 0,003125 bei INA238)
V_aus   = roh / 1024 · 2 / 0,0636      alle übrigen Typen
I_aus   = Σ max(0, (roh_k − Nullpunkt_k) · Faktor_k)   solange Statusbit 0 gesetzt ist
```

### Fehlersuche

**Das Gerät taucht nicht in der GX-Geräteliste auf.** Zuerst ins Log schauen:

```bash
tail -f /var/log/TsBuckBoost/current
```

multilog beginnt alle 25 kB eine neue Datei; zeigt `tail -f` keine neuen Zeilen mehr,
einfach neu starten.

`no converter answers, skipping` heißt, dass der Port gefunden wurde, dort aber nichts
mit bekannter Kennung antwortet — meist hält jemand anderes den Port, siehe unten.
`does not answer` zusammen mit `no converter found (round n), next try in … s` heißt,
dass der gemerkte Port da, aber stumm ist: Der Wandler ist aus oder ohne Versorgung,
und der Treiber fragt mit wachsenden Pausen weiter. `belongs to another driver,
skipping` heißt, dass ein anderer Prozess diesen Port offen hält. `model not
supported, port left alone` heißt, dass ein alter Kurzblock-Wandler geantwortet hat
(siehe Voraussetzungen). `short answer to the calibration query` heißt, dass das
Auslesen beim Start gestört wurde; der Treiber startet dann neu, statt mit unbekannten
Nullpunkten zu laufen, und hat beim nächsten Versuch normalerweise Erfolg.
`implausible block` heißt, dass ein Messwert verworfen wurde, der nicht echt sein
kann; viele davon deuten auf fremden Verkehr auf der Leitung. `line settings …
changed underneath us` heißt, dass ein anderer Prozess den Port umgestellt hat; der
Treiber startet neu und sendet nichts, bis er ihn frisch geöffnet hat. `polls without
an answer - restarting` heißt, dass der Port tot ist, etwa nach einer
USB-Neuenumeration; der Neustart öffnet ihn neu.

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

Danach wieder starten mit `svc -u /service/TsBuckBoost` — bis dahin bleibt der Dienst
aus, auch wenn die Sitzung zwischendurch abbricht. Neu starten mit
`svc -t /service/TsBuckBoost`.

**`ttyUSB`-Nummern wandern.** Nach einem Neustart oder Umstecken kann `ttyUSB1` ein
ganz anderes Gerät sein als gestern. Der Treiber löst seinen Port deshalb über
`/dev/serial/by-id/` auf und verifiziert ihn über die Typabfrage des Protokolls.
Die CP210x-Ports zeigt der folgende Befehl — der Treiber überspringt die, die ein
anderer Treiber offen hält, und fragt nach seinem ersten Start nur den gemerkten:

```bash
/data/TsBuckBoost/find-port.sh
```

Für einen manuellen Test an einem bestimmten Port diesen als Argument übergeben — dann
sucht der Treiber nicht, rührt den serial-starter nicht an und merkt sich den Port
nicht:

```bash
python3 /data/TsBuckBoost/dbus-tsbb.py /dev/serial/by-id/usb-Silicon_Labs_CP2102N_…-port0
```

**Der Strom bleibt auf null.** Das ist meistens richtig so: Der Treiber meldet Strom
nur, solange Statusbit 0 gesetzt ist — genau wie TSConfig. Der Wandler startet
verzögert und erst, wenn die Eingangsspannung seine Einschaltschwelle übersteigt
(Einstellung 57, ab Werk 13,3 V). Eine Lichtmaschine, die im Standlauf darunter
bleibt, löst ihn nicht aus. Wer über Pin 1 einen Lüfter schaltet, hat mit dessen
Geräusch die zuverlässigste Anzeige dafür, wann der Wandler wirklich arbeitet.

**VRM zeigt die falsche Geräteinstanz.** Sie steht in
`/Settings/Devices/tsbuckboost/ClassAndVrmInstance` und ist mit `alternator:40` vorbelegt.
Bei einer Kollision dort ändern und den Dienst neu starten. Die separaten
Temperaturgeräte führen ihre in `/Settings/Devices/tsbuckboost_board/ClassAndVrmInstance`
und den Geschwistern.

### Lüfterhalterung

Eine druckbare Halterung für einen 80-mm-Lüfter am Buck-Boost 50 A, als STEP und STL,
liegt im eigenen Branch [`hardware`](https://github.com/mcgyver78/TsBuckBoost/tree/hardware)
— bewusst außerhalb des Pakets,
damit SetupHelper sie nicht auf jedes GX-Gerät kopiert. Der Wandler regelt bei Wärme
zurück, ein langsam laufender Lüfter hält den Ladestrom in einem warmen Schacht also oben
und macht die Temperaturwerte von oben erst richtig interessant. Für den Treiber wird sie
nicht gebraucht.

### Geprüft mit

Buck-Boost 50 A (Kennung 113 / TS800C5) in einem 12 → 24 V Aufbau, gegen SmartShunt
und BMS als Referenz: Ausgangsspannung 26,89 V gegen 26,88 V, Ausgangsstrom 27,56 A
gegen 26,93 A am Shunt — die Differenz ist die Systemlast, die vor dem Shunt abgeht.

### Lizenz

MIT
