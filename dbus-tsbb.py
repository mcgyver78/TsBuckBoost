#!/usr/bin/env python3
"""
dbus-tsbb.py — meldet einen Victron Buck-Boost DC-DC-Wandler (OEM: top systems
TS 400/800/1600) auf dem D-Bus von Venus OS als com.victronenergy.dcdc an.

Der Wandler hat keinen VE.Direct-Port; sein USB-Serial-Protokoll wurde aus der
Windows-Software TSConfig v2.4.4 rekonstruiert. Es werden ausschliesslich
Lesekommandos gesendet (FE 11 = lesen, FE D0 = Live-Block).
Schreibende Kommandos sind bewusst nicht implementiert.

Aufruf ohne Argument: der Port wird unter /dev/serial/by-id/ gesucht.
"""
import glob
import os
import sys
import time

import serial
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

for _p in ("/opt/victronenergy/dbus-systemcalc-py/ext/velib_python",
           "/opt/victronenergy/velib_python",
           os.path.join(os.path.dirname(__file__), "velib_python")):
    if os.path.isdir(_p):
        sys.path.insert(1, _p)
        break
from vedbus import VeDbusService  # noqa: E402

VERSION = "1.1"
POLL_MS = 2000
FALLBACK_INSTANCE = 40

# Geraetekennungen, Antwort auf FE 11 1F F2 01
IDS = {54: "TS800", 63: "TS400", 71: "TS800C", 73: "TS200", 82: "TS100",
       85: "TS1600", 87: "TS4002", 89: "TS800C2", 97: "TS16002",
       98: "TS4003", 108: "TS800C3", 112: "TSEV1000", 113: "TS800C5"}
# interner Typ, nach dem TSConfig seine Formeln auswaehlt
INTERNAL = {"TS800C5": "TS800C3", "TS4003": "TS4002"}
# diese Typen rechnen die Ausgangsspannung ueber den Shunt-Faktor
SPFACTOR_VOUT = {"TS800C3", "TSEV1000", "TS16002"}
LONG_BLOCK = {"TS1600", "TS16002", "TS800C2", "TS800C3", "TSEV1000",
              "TS4002", "TS100"}


def log(msg):
    print("%s %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def signed(v):
    return v - 256 if v > 127 else v


# Byte 21 des Live-Blocks. Bit 0 und Bit 5 sind am Geraet verifiziert,
# Bit 1 und Bit 3 sind aus dem Betriebsverlauf abgeleitet.
STATUS_BITS = ((0x01, "wandelt"), (0x02, "freigegeben, wartet"),
               (0x08, "Nachlauf"), (0x20, "ueber Pin 1 gesperrt"))


def describe(status):
    names = [n for bit, n in STATUS_BITS if status & bit]
    return ", ".join(names) if names else "aus"


def find_port():
    for pattern in ("/dev/serial/by-id/*CP210*", "/dev/serial/by-id/*cp210*"):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[0]
    return None


class Converter(object):
    """Serielle Anbindung an den Wandler, read-only."""

    def __init__(self, port):
        self.port = port
        self.ser = serial.Serial(port, 9600, 8, "N", 1, timeout=0.5)
        try:
            self.ser.dtr = True
            self.ser.rts = True
        except OSError:
            pass
        time.sleep(0.3)
        self._read_identity()

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def _ask(self, frame, nrec, timeout=1.0):
        # Sicherung: dieser Treiber sendet ausschliesslich Lesekommandos
        if frame[0] != 0xFE or frame[1] not in (0x11, 0xD0, 0xCF):
            raise ValueError("nur Lesekommandos erlaubt")
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()
        end = time.time() + timeout
        buf = b""
        while len(buf) < nrec and time.time() < end:
            chunk = self.ser.read(nrec - len(buf))
            if chunk:
                buf += chunk
        return buf

    def _read(self, page, addr, length, timeout=1.5):
        return self._ask(bytes([0xFE, 0x11, page, addr, length]), length, timeout)

    def _read_identity(self):
        r = self._read(0x1F, 0xF2, 1)
        if not r:
            raise IOError("keine Antwort auf die Typabfrage")
        self.device_id = r[0]
        if self.device_id not in IDS:
            raise IOError("unbekannte Geraetekennung %d - kein TS-Wandler?" % self.device_id)
        self.name = IDS[self.device_id]
        self.ctype = INTERNAL.get(self.name, self.name)
        self.block_len = 22 if self.ctype in LONG_BLOCK else 19

        ina = self._read(0x1F, 0xF5, 1)
        self.ina = ina[0] if ina else 1
        self.spfactor = 0.003125 if self.ina == 2 else 0.00125

        e0 = self._read(0x1F, 0xE0, 16)
        self.sf = [e0[0] / 1000.0, e0[1] / 1000.0, e0[2] / 1000.0] if len(e0) >= 3 else [0.0, 0.0, 0.0]

        cal = b""
        for length in (0x40, 0x30, 0x20):
            cal = self._read(0x1F, 0x2A, length, 2.5)
            if len(cal) == length:
                break
        self.offsets = list(cal[41:44]) if len(cal) >= 44 else [0, 0, 0]

        fw = self._read(0x00, 0xD0, 8)
        self.firmware = fw.hex() if fw else ""
        log("erkannt: %s (ID %d, intern %s), %s, Faktoren %s, Nullpunkte %s"
            % (self.name, self.device_id, self.ctype,
               "INA238" if self.ina == 2 else "INA226", self.sf, self.offsets))

    def read(self):
        b = self._ask(bytes([0xFE, 0xD0]), self.block_len)
        if len(b) != self.block_len:
            return None
        status = b[21] if len(b) > 21 else 0
        active = bool(status & 0x01)           # Bit 0: Wandler wandelt
        blocked = bool(status & 0x20)          # Bit 5: ueber Pin 1 gesperrt
        current = 0.0
        if active:
            for k in range(3):
                raw = b[2 * k] * 256 + b[2 * k + 1]
                current += max(0.0, (raw - self.offsets[k]) * self.sf[k])
        v_raw = b[10] * 256 + b[11]
        v_out = v_raw * self.spfactor if self.ctype in SPFACTOR_VOUT \
            else v_raw / 1024.0 * 2.0 / 0.0636
        v_in = (b[12] * 256 + b[13]) / 1024.0 * 2.0 / 0.0636
        return {"v_in": round(v_in, 2),
                "v_out": round(v_out, 2),
                "current": round(current, 2),
                "power": round(v_out * current, 1),
                "active": active,
                "blocked": blocked,
                "status": status,
                "t_mosfet": signed(b[20]),
                "t_board": signed(b[18]),
                "t_pcb": signed(b[19])}


def device_instance(bus, name):
    """VRM-Instanz ueber die Venus-Settings holen, damit sie stabil bleibt."""
    try:
        from settingsdevice import SettingsDevice
        s = SettingsDevice(bus, {
            "instance": ["/Settings/Devices/%s/ClassAndVrmInstance" % name,
                         "dcdc:%d" % FALLBACK_INSTANCE, 0, 0]},
            eventCallback=None, timeout=10)
        return int(str(s["instance"]).split(":")[1])
    except Exception as e:
        log("Settings nicht verfuegbar (%s), nutze Instanz %d" % (e, FALLBACK_INSTANCE))
        return FALLBACK_INSTANCE


class Driver(object):
    def __init__(self, port):
        self.port = port
        self.last_status = None
        self.conv = Converter(port)
        bus = dbus.SystemBus()
        instance = device_instance(bus, "tsbuckboost")
        svcname = "com.victronenergy.dcdc.tsbb_%s" % os.path.basename(
            os.path.realpath(port))
        try:
            self.svc = VeDbusService(svcname, bus=bus, register=False)
            deferred = True
        except TypeError:                      # aeltere velib_python
            self.svc = VeDbusService(svcname, bus=bus)
            deferred = False

        s = self.svc
        s.add_path("/Mgmt/ProcessName", os.path.basename(__file__))
        s.add_path("/Mgmt/ProcessVersion", VERSION)
        s.add_path("/Mgmt/Connection", port)
        s.add_path("/DeviceInstance", instance)
        s.add_path("/ProductId", 0xFFFF)
        s.add_path("/ProductName", "Buck-Boost %s" % self.conv.name)
        s.add_path("/FirmwareVersion", self.conv.firmware)
        s.add_path("/Serial", "%s-%d" % (self.conv.ctype, self.conv.device_id))
        s.add_path("/Connected", 1)
        # /Mode spiegelt den Freigabeeingang an Pin 1 wider: 1 = freigegeben,
        # 4 = gesperrt. Nur lesbar - der Wandler laesst sich ueber diese
        # Schnittstelle nicht schalten, nur ueber die Hardware an Pin 1.
        s.add_path("/Mode", 1)
        s.add_path("/State", 0)                # 0 = Aus, 3 = Bulk
        for p in ("/Dc/0/Voltage", "/Dc/0/Current", "/Dc/0/Power",
                  "/Dc/In/V", "/Dc/0/Temperature"):
            s.add_path(p, None)
        if deferred:
            s.register()
        log("angemeldet als %s, Instanz %d" % (svcname, instance))

    def update(self):
        try:
            d = self.conv.read()
        except Exception as e:
            log("Lesefehler: %s" % e)
            d = None
        if d is None:
            self.svc["/Connected"] = 0
            self.svc["/State"] = 0
            self.svc["/Dc/0/Current"] = 0
            self.svc["/Dc/0/Power"] = 0
            if not os.path.exists(self.port):
                log("Port verschwunden - Neustart des Dienstes")
                sys.exit(1)                    # daemontools startet neu
            return True
        s = self.svc
        s["/Connected"] = 1
        s["/Dc/0/Voltage"] = d["v_out"]
        s["/Dc/0/Current"] = d["current"]
        s["/Dc/0/Power"] = d["power"]
        s["/Dc/In/V"] = d["v_in"]
        s["/Dc/0/Temperature"] = d["t_mosfet"]
        s["/State"] = 3 if d["active"] else 0
        s["/Mode"] = 4 if d["blocked"] else 1
        if d["status"] != self.last_status:
            log("Status 0x%02X: %s" % (d["status"], describe(d["status"])))
            self.last_status = d["status"]
        return True


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    port = sys.argv[1] if len(sys.argv) > 1 else find_port()
    if not port:
        log("kein CP210x-Port unter /dev/serial/by-id/ gefunden")
        time.sleep(10)
        sys.exit(1)
    log("nutze Port %s" % port)
    driver = Driver(port)
    driver.update()
    GLib.timeout_add(POLL_MS, driver.update)
    GLib.MainLoop().run()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("Abbruch: %s" % exc)
        time.sleep(10)                         # daemontools nicht ueberrennen
        sys.exit(1)
