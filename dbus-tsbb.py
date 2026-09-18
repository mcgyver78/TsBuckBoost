#!/usr/bin/env python3
"""
dbus-tsbb.py — publishes a Victron Buck-Boost DC-DC converter (OEM: top systems
TS 400/800/1600) on the Venus OS D-Bus as com.victronenergy.alternator.

The converter has no VE.Direct port; its USB serial protocol was reconstructed
from the Windows tool TSConfig v2.4.4. Only read commands are ever sent
(FE 11 = read, FE D0 = live block, FE CF = auxiliary block). Write commands
are deliberately not implemented — the same interface accepts parameter changes
and firmware updates, so a wrong address could alter charge settings or enter
the bootloader. Every byte for the converter goes through send_read(), which
refuses anything else, and refuses to send at all once another process has
changed the line settings underneath us.

Called without an argument, the driver asks the port it confirmed as the
converter last time (kept in the settings), and only that port while it
exists. On the first start, or when that port is gone, every CP210x port
under /dev/serial/by-id/ is probed with the type query; only the port that
answers is taken away from serial-starter.
"""
import fcntl
import glob
import math
import os
import signal
import struct
import subprocess
import sys
import termios
import time


def log(msg):
    print("%s %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


try:
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
except ImportError as _e:
    # Without this pause a missing module restarts the service once a second.
    log("aborted: %s" % _e)
    time.sleep(10)
    sys.exit(1)

VERSION = "1.21"
POLL_MS = 2000
FALLBACK_INSTANCE = 40
# After this many consecutive failed polls the process exits and daemontools
# restarts it — that reopens the port, which is the only cure for a file
# descriptor that went dead when the USB device re-enumerated.
MAX_READ_ERRORS = 5
STOP_TTY = "/opt/victronenergy/serial-starter/stop-tty.sh"
# serial-starter keeps a node here for every tty it still manages, and a driver
# that claims a port removes it. A candidate without that node is therefore not
# free but taken - by a driver that will keep talking on it. Probing it would
# garble that driver's traffic; on a Cerbo with an Autoterm heater sharing its
# port with Venus probe services, the heater answered 2 of 30 queries instead
# of 29 of 29.
SERIAL_STARTER_DIR = "/dev/serial-starter"
# systemcalc sums /Dc/Alternator/Power over com.victronenergy.alternator only —
# com.victronenergy.dcdc never reaches the overview page. Victron files DC-DC
# converters under alternator as well ("This also includes other DC/DC
# converters." in delegates/dvcc.py).
SERVICE_CLASS = "alternator"
# All settings of this driver live under /Settings/Devices/<this>/.
SETTINGS_NAME = "tsbuckboost"
# /DeviceOffReason is a bitmask answering "why is the charger off?".
# 0x08 = remote connector, which is exactly the enable input on pin 1.
OFF_REASON_REMOTE_CONNECTOR = 0x08
# The CAN temperature sensor reports -101 when none is connected.
# TSConfig writes "no signal" into the field in that case.
CAN_TEMP_NO_SIGNAL = -101
# Temperature alarm on the MOSFETs. The converter starts limiting current at
# 85 °C by default, so warn well below that. Released again with hysteresis.
TEMP_WARNING = 75
TEMP_ALARM = 85
TEMP_HYSTERESIS = 5
# A level is only entered after this many readings in a row at or above its
# threshold. The line has no checksum, and one garbled block must not raise
# an alarm; a real overtemperature lasts longer than two polls.
ALARM_CONFIRM_POLLS = 2
# The alarm level survives a restart of the process in this directory (tmpfs,
# cleared by a reboot), so that the hysteresis does not start again at 0.
STATE_DIR = "/run/tsbuckboost"
ALARM_STATE_MAX_AGE = 120
# Only write the energy counter to the settings every few minutes - and on
# every orderly end of the process. After a failed write, try again sooner.
ENERGY_SAVE_INTERVAL = 300
ENERGY_RETRY = 30
# Longest gap between two readings that is still counted as energy. After an
# outage the first reading starts a new interval instead of booking the gap.
MAX_ENERGY_DT = 10.0
# Bounds for a live block that can be a real reading. The protocol has no
# checksum: a block that lost a byte, or caught foreign traffic, decodes into
# numbers like 2000 V and 19 000 A, and a single such poll would put tens of
# kWh into the energy counter. These bounds are far outside anything the
# supported units deliver and only catch nonsense.
MAX_VOLTAGE = 100.0
MAX_CURRENT = 250.0
# After this many polls without an answer to FE CF (a unit without the
# auxiliary block, or no CAN bus), it is only asked every AUX_RETRY_POLLS
# polls - each unanswered question costs half a second.
AUX_MISSES = 3
AUX_RETRY_POLLS = 30
# Pauses between searches while no converter answers: quick at first (a
# converter still powering up), then longer, so that foreign CP210x devices
# are not asked every few seconds for hours. A new port ends the wait.
SEARCH_DELAYS = (10, 20, 40, 80, 160, 300)
PORT_WATCH = 5
# Optional: publish each temperature as its own Venus device.
# Off by default; switch on with
#   dbus -y com.victronenergy.settings \
#        /Settings/Devices/tsbuckboost/SeparateTempSensors SetValue 1
# The driver restarts itself to apply it; then restart the GUI as well
# (svc -t /service/start-gui), or the device list keeps dead entries.
TEMP_SENSORS = (("Board", "t_board", "Board", 41),
                ("Mosfet1", "t_mosfet1", "MOSFET 1", 42),
                ("Mosfet2", "t_mosfet2", "MOSFET 2", 43),
                ("CanSensor", "t_can", "CAN sensor", 44))

# Device ids, the answer to FE 11 1F F2 01
IDS = {54: "TS800", 63: "TS400", 71: "TS800C", 73: "TS200", 82: "TS100",
       85: "TS1600", 87: "TS4002", 89: "TS800C2", 97: "TS16002",
       98: "TS4003", 108: "TS800C3", 112: "TSEV1000", 113: "TS800C5"}
# internal type TSConfig picks its formulas by
INTERNAL = {"TS800C5": "TS800C3", "TS4003": "TS4002"}
# these types compute the output voltage through the shunt factor
SPFACTOR_VOUT = {"TS800C3", "TSEV1000", "TS16002"}
# Input voltage divider per type; TSConfig uses 0.13 for the TSEV1000 only
VIN_DIVIDER = {"TSEV1000": 0.13}
VIN_DIVIDER_DEFAULT = 0.0636
# Output voltage divider of the types outside SPFACTOR_VOUT. It has the same
# value as VIN_DIVIDER_DEFAULT but is a different pair of resistors, so it is
# a constant of its own.
VOUT_DIVIDER = 0.0636
# Types that answer FE D0 with the 22-byte block this driver decodes. The
# older types (TS200/400/800/800C, ids 73/63/54/71) use a 19-byte block with
# a different layout; they are rejected at start-up rather than misread.
LONG_BLOCK = {"TS1600", "TS16002", "TS800C2", "TS800C3", "TSEV1000",
              "TS4002", "TS100"}
BLOCK_LEN = 22
# Ids the probe accepts. An old short-block type is logged and left with
# serial-starter, instead of being taken away from it and rejected afterwards.
SUPPORTED_IDS = frozenset(i for i, n in IDS.items() if INTERNAL.get(n, n) in LONG_BLOCK)

# The only frames this driver ever sends start with FE and one of these.
READ_OPCODES = (0x11, 0xD0, 0xCF)
TYPE_QUERY = bytes([0xFE, 0x11, 0x1F, 0xF2, 0x01])
# How long a line has to stay quiet before the type query, and how long the
# probe listens after each answer.
PROBE_QUIET = 0.2
# The answer to the type query is the id, one byte - so says the protocol as
# read from TSConfig; on the converter itself that is not measured. A short
# answer that starts with the same id both times therefore still counts, and
# the extra bytes are logged. A device that streams sends more than this
# within PROBE_QUIET.
TYPE_ANSWER_MAX = 4
CRTSCTS = getattr(termios, "CRTSCTS", 0)


def signed(v):
    return v - 256 if v > 127 else v


def exit_process(code):
    """End the process now; daemontools starts it again. os._exit works from
    any callback, whatever GLib or dbus-python do with an exception there."""
    sys.stdout.flush()
    os._exit(code)


# Byte 21 of the live block. Bit 0 and bit 5 are verified against the device,
# bit 1 and bit 3 are inferred from observed behaviour.
STATUS_BITS = ((0x01, "converting"), (0x02, "enabled, waiting"),
               (0x08, "run-on"), (0x20, "disabled by pin 1"))


def describe(status):
    names = [n for bit, n in STATUS_BITS if status & bit]
    return ", ".join(names) if names else "off"


def private_bus():
    """A D-Bus connection of its own.

    VeDbusService attaches a handler to the root path "/", and there can only
    be one per connection. Several services in one process therefore each need
    their own connection, otherwise the second one fails with
    "there is already a handler".
    """
    try:
        return dbus.SystemBus(private=True)
    except Exception:
        addr = os.environ.get("DBUS_SYSTEM_BUS_ADDRESS",
                              "unix:path=/var/run/dbus/system_bus_socket")
        return dbus.bus.BusConnection(addr)


class LineChanged(IOError):
    """Another process has changed the line settings of our tty."""


def line_is_ours(ser):
    """True while the tty is still set the way pyserial opened it: 9600 8N1,
    raw, no flow control.

    termios belongs to the tty, not to the file descriptor. Any process that
    opens the port - a serial-starter probe, another driver - and sets its own
    speed changes it for us as well, and the exclusive flag does not keep out
    a process that does not lock. A read command sent at a foreign speed
    reaches the converter as different bytes: at 4800 baud FE CF arrives as
    F8 FE F8, an opcode that is not one of ours.
    """
    try:
        iflag, oflag, cflag, _lflag, ispeed, ospeed, _cc = termios.tcgetattr(ser.fileno())
    except Exception:
        return False
    return (ispeed == termios.B9600 and ospeed == termios.B9600
            and (cflag & termios.CSIZE) == termios.CS8
            and not cflag & (termios.PARENB | termios.CSTOPB | CRTSCTS)
            and not iflag & (termios.IXON | termios.IXOFF | termios.ISTRIP)
            and not oflag & termios.OPOST)


def send_read(ser, frame):
    """The only place where bytes go to the converter.

    Read commands only, and only while the line is still ours - otherwise
    nothing is sent at all. No flush(): tcdrain has no time limit, and the
    read that follows waits for the answer anyway.
    """
    frame = bytes(frame)
    if len(frame) < 2 or frame[0] != 0xFE or frame[1] not in READ_OPCODES:
        raise ValueError("read commands only, refused %s" % frame.hex())
    if not line_is_ours(ser):
        raise LineChanged("line settings of %s changed underneath us - nothing sent"
                          % ser.port)
    ser.write(frame)


def open_serial(port, exclusive=False, announce=False):
    """The port at 9600 8N1 with a short read timeout.

    exclusive is an advisory flock in pyserial: it keeps out other drivers
    that lock as well, nothing else. pyserial before 3.3 does not know it;
    then the port is opened without.
    """
    kwargs = dict(baudrate=9600, bytesize=8, parity="N", stopbits=1, timeout=0.5)
    try:
        ser = serial.Serial(port, exclusive=exclusive, **kwargs)
    except TypeError:
        if announce:
            log("this pyserial cannot lock ports - %s opened without a lock" % port)
        ser = serial.Serial(port, **kwargs)
    # A write that cannot drain - a stuck USB bridge - must not hang the poll.
    try:
        ser.write_timeout = 1.0
    except Exception:
        pass
    return ser


def candidate_ports():
    """All CP210x ports by stable name, in a deterministic order."""
    hits = set()
    for pattern in ("/dev/serial/by-id/*CP210*", "/dev/serial/by-id/*cp210*"):
        hits.update(glob.glob(pattern))
    return sorted(hits)


class LineState(object):
    """The line settings and modem lines of a tty as another process left them.

    Opening a port with pyserial sets 9600 8N1 raw and raises DTR/RTS - for
    every process that has the tty open, since termios belongs to the tty. A
    service that runs a foreign device at another speed read nothing but
    garbage after a probe, until it opened the port again. The probe
    therefore puts back what it found. Nothing is sent to do so.
    """

    def __init__(self, port):
        self.fd = None
        self.attrs = None
        self.bits = None
        try:
            self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError:
            return
        try:
            self.attrs = termios.tcgetattr(self.fd)
        except (termios.error, OSError):
            pass
        try:
            self.bits = fcntl.ioctl(self.fd, termios.TIOCMGET, struct.pack("I", 0))
        except (OSError, AttributeError):
            pass

    def restore(self):
        if self.fd is None:
            return
        try:
            if self.attrs is not None:
                termios.tcsetattr(self.fd, termios.TCSANOW, self.attrs)
            if self.bits is not None:
                fcntl.ioctl(self.fd, termios.TIOCMSET, self.bits)
        except (termios.error, OSError, AttributeError):
            pass
        finally:
            os.close(self.fd)
            self.fd = None


# _probe_once(): the port behaved like anything but a converter, leave it.
SKIP = "skip"


def _probe_once(port):
    """One session on a port: the id if it answered like a converter, SKIP if
    it talked unasked, sent more than a short answer, disagreed with itself or
    could not be used, None if it stayed silent."""
    try:
        ser = open_serial(port, exclusive=True)
    except (OSError, serial.SerialException):
        # gone, or locked by another driver that opens exclusively
        return SKIP
    try:
        try:
            ser.dtr = True
            ser.rts = True
        except OSError:
            pass
        time.sleep(0.3)
        ser.reset_input_buffer()
        time.sleep(PROBE_QUIET)
        if ser.in_waiting:
            return SKIP         # talks without being asked: nothing is written
        answers = []
        for _ in range(2):
            ser.reset_input_buffer()
            send_read(ser, TYPE_QUERY)
            r = ser.read(1)
            if not r:
                return None
            time.sleep(PROBE_QUIET)
            more = ser.in_waiting
            if len(r) + more > TYPE_ANSWER_MAX:
                return SKIP     # a stream, not an answer
            if more:
                r += ser.read(more)
            answers.append(bytes(r))
        ids = [a[0] for a in answers]
        if ids[0] != ids[1] or ids[0] not in IDS:
            return SKIP
        if any(len(a) > 1 for a in answers):
            log("%s answers the type query with more than its id: %s"
                % (port, " / ".join(a.hex() for a in answers)))
        return ids[0]
    except LineChanged as e:
        log("%s - %s skipped" % (e, port))
        return SKIP
    except (OSError, serial.SerialException):
        return SKIP
    finally:
        try:
            ser.close()
        except Exception:
            pass


def probe_identity(port, attempts=4):
    """Ask a port for the converter id without taking it away from anyone.

    A converter says nothing unless asked and answers the type query with its
    id, one byte. A foreign device that talks on its own - a GPS, a BMS -
    sends whether asked or not, and 13 of the 256 byte values are ids, all of
    them printable ASCII. So the line has to be quiet before the question,
    the answer has to be short, and two answers in a row have to name the
    same id; a talking port is left before anything is written into it.

    serial-starter may be probing the same port and take the answer away, so
    a silent attempt is repeated. Returns the device id, or None.
    """
    for attempt in range(attempts):
        if attempt:
            time.sleep(0.5)
            # whoever held the port may have come back in the meantime
            if owned_by_another_driver(port):
                return None
        saved = LineState(port)
        try:
            answer = _probe_once(port)
        finally:
            saved.restore()
        if answer == SKIP:
            return None
        if answer is not None:
            return answer
    return None


def release_from_serial_starter(port, timeout=15, settle=1.0, quiet=False):
    """Tell serial-starter to leave this tty alone. Only for the port that
    actually answered as a converter — a foreign CP210x device must keep its
    own service. Returns True if stop-tty.sh ran without an error."""
    tty = os.path.basename(os.path.realpath(port))
    if not os.path.exists(STOP_TTY):
        log("%s missing - serial-starter keeps %s" % (STOP_TTY, tty))
        return False
    try:
        rc = subprocess.call([STOP_TTY, tty], timeout=timeout)
    except Exception as e:
        log("could not run stop-tty.sh for %s: %s" % (tty, e))
        return False
    if rc != 0:
        log("stop-tty.sh %s failed with exit code %d" % (tty, rc))
        return False
    if not quiet:
        log("released %s from serial-starter" % tty)
    if settle:
        time.sleep(settle)
    return True


def port_open_elsewhere(tty):
    """True if a process other than this one holds /dev/<tty> open.

    Read from /proc, the only place on Venus that knows. Anything unreadable
    is skipped rather than guessed at: a port is declared busy on evidence,
    never on the absence of it.
    """
    ziel = os.path.realpath(os.path.join("/dev", tty))
    selbst = str(os.getpid())
    try:
        pids = os.listdir("/proc")
    except OSError:
        return False
    for pid in pids:
        if not pid.isdigit() or pid == selbst:
            continue
        verzeichnis = "/proc/%s/fd" % pid
        try:
            deskriptoren = os.listdir(verzeichnis)
        except OSError:
            continue
        for fd in deskriptoren:
            try:
                if os.path.realpath(os.path.join(verzeichnis, fd)) == ziel:
                    return True
            except OSError:
                continue
    return False


def owned_by_another_driver(port):
    """True if some other driver has already claimed this port for itself.

    While serial-starter keeps a node for the tty, the port is serial-
    starter's and ours to take. Without the node it is claimed - but not
    necessarily by somebody else: THIS driver removes the node too when it
    claims a port, and it does not come back until the next reboot. Reading
    "no node" as "foreign" locks the driver out of its own port after every
    restart of the service; that happened to the MaxxFan driver, whose card
    disappeared from a customer system for exactly this reason.

    So a port without a node is only left alone when another process really
    holds it open - a fact, readable in /proc, instead of a guess.

    Where /dev/serial-starter does not exist (not a GX, or an older Venus)
    there is nothing to conclude and the port is probed as before.
    """
    if not os.path.isdir(SERIAL_STARTER_DIR):
        return False
    tty = os.path.basename(os.path.realpath(port))
    if os.path.exists(os.path.join(SERIAL_STARTER_DIR, tty)):
        return False
    return port_open_elsewhere(tty)


def find_port(preferred=None, verbose=True):
    """The by-id path of the converter, already taken away from serial-starter,
    or None.

    The port confirmed last time is asked first and, while it exists, as the
    only one: present but silent means the converter is off, and asking
    foreign ports again would only disturb them. It is released from
    serial-starter before the question, so that no probe service talks in
    between; its by-id name carries the serial number of the converter's own
    USB bridge. Only on the first start, or when it is gone, are all
    candidates asked.
    """
    ports = candidate_ports()
    if not ports:
        if verbose:
            log("no CP210x port found under /dev/serial/by-id/")
        return None
    if preferred in ports:
        release_from_serial_starter(preferred, quiet=not verbose)
        dev_id = probe_identity(preferred)
        if dev_id in SUPPORTED_IDS:
            log("%s answers as %s (id %d)" % (preferred, IDS[dev_id], dev_id))
            return preferred
        if verbose:
            log("%s, the converter's port, does not answer" % preferred)
        return None
    for port in ports:
        if owned_by_another_driver(port):
            # A converter that has just been plugged in is always under
            # serial-starter, so nothing that should be found is lost here.
            if verbose:
                log("%s belongs to another driver, skipping" % port)
            continue
        dev_id = probe_identity(port)
        if dev_id is None:
            if verbose:
                log("%s: no converter answers, skipping" % port)
            continue
        if dev_id not in SUPPORTED_IDS:
            log("%s answers as %s (id %d) - model not supported, port left alone"
                % (port, IDS[dev_id], dev_id))
            continue
        log("%s answers as %s (id %d)" % (port, IDS[dev_id], dev_id))
        release_from_serial_starter(port)
        return port
    return None


def wait_for_ports(seconds):
    """Sleep, but come back early when the set of candidate ports changes.
    Returns True in that case."""
    before = candidate_ports()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(min(PORT_WATCH, max(0.0, end - time.monotonic())))
        if candidate_ports() != before:
            return True
    return False


def search(settings):
    """Look for the converter until it answers, and return its port.

    Up to v1.20 the process ended after one round and daemontools started it
    again: a new interpreter every 15 seconds, and without a converter every
    foreign CP210x port asked again, for hours, until the log held nothing
    but the loop. Now the process stays and waits longer each round.
    """
    preferred = stored_port(settings)
    rounds = 0
    verbose = True
    while True:
        port = find_port(preferred, verbose)
        if port:
            return port
        delay = SEARCH_DELAYS[min(rounds, len(SEARCH_DELAYS) - 1)]
        rounds += 1
        if verbose or rounds in (2, 4, 8) or rounds % 16 == 0:
            log("no converter found (round %d), next try in %d s" % (rounds, delay))
        verbose = wait_for_ports(delay)


def implausible(v_in, v_out, channels):
    """Why a decoded live block cannot be a real reading, or None if it can.
    Channel currents only count while the converter is converting; at rest
    they are not used and not checked."""
    for name, value in (("input", v_in), ("output", v_out)):
        if not 0.0 <= value <= MAX_VOLTAGE:
            return "%s voltage %.1f V" % (name, value)
    for k, amps in enumerate(channels):
        if amps > MAX_CURRENT:
            return "channel %d %.0f A" % (k + 1, amps)
    if sum(channels) > MAX_CURRENT:
        return "current %.0f A" % sum(channels)
    return None


class Converter(object):
    """Serial link to the converter, read-only."""

    def __init__(self, port):
        self.port = port
        # Exclusive, so that other drivers that lock as well do not open this
        # port underneath us. It is an advisory flock: a probe or driver that
        # does not lock gets in all the same, which is why send_read() checks
        # the line settings before every frame.
        self.ser = open_serial(port, exclusive=True, announce=True)
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
        self.ser.reset_input_buffer()
        send_read(self.ser, frame)
        end = time.monotonic() + timeout
        buf = b""
        while len(buf) < nrec and time.monotonic() < end:
            chunk = self.ser.read(nrec - len(buf))
            if chunk:
                buf += chunk
        return buf

    def _read(self, page, addr, length, timeout=1.5):
        return self._ask(bytes([0xFE, 0x11, page, addr, length]), length, timeout)

    def _read_identity(self):
        r = self._read(0x1F, 0xF2, 1)
        if not r:
            raise IOError("no answer to the type query")
        self.device_id = r[0]
        if self.device_id not in IDS:
            raise IOError("unknown device id %d - not a TS converter?" % self.device_id)
        self.name = IDS[self.device_id]
        self.ctype = INTERNAL.get(self.name, self.name)
        if self.ctype not in LONG_BLOCK:
            raise IOError("%s (id %d) uses the short data block, which this "
                          "driver does not decode - model not supported"
                          % (self.name, self.device_id))
        self.block_len = BLOCK_LEN
        self.vin_divider = VIN_DIVIDER.get(self.ctype, VIN_DIVIDER_DEFAULT)

        # Every calibration value below feeds the current calculation. A short
        # answer is not "use a default", it is "we do not know" - and a wrong
        # zero point turns 27 A into 98 A on the display and in the energy
        # counter. So each one is fatal; daemontools restarts us and the next
        # attempt usually succeeds.
        ina = self._read(0x1F, 0xF5, 1)
        if len(ina) != 1:
            raise IOError("no answer to the current-sense chip query")
        self.ina = ina[0]
        self.spfactor = 0.003125 if self.ina == 2 else 0.00125

        e0 = self._read(0x1F, 0xE0, 16)
        if len(e0) < 3:
            raise IOError("short answer to the current-factor query (%d bytes)" % len(e0))
        self.sf = [e0[0] / 1000.0, e0[1] / 1000.0, e0[2] / 1000.0]
        if not all(self.sf):
            raise IOError("current factors read as zero: %s" % self.sf)

        # The zero points are bytes 41-43, so only answers of at least 44
        # bytes are of any use. A complete answer wins; otherwise the longest.
        cal = b""
        for length in (0x40, 0x30):
            answer = self._read(0x1F, 0x2A, length, 2.5)
            if len(answer) == length:
                cal = answer
                break
            if len(answer) > len(cal):
                cal = answer
        if len(cal) < 44:
            raise IOError("short answer to the calibration query (%d bytes)" % len(cal))
        self.offsets = list(cal[41:44])

        fw = self._read(0x00, 0xD0, 8)
        # TSConfig shows the firmware as text ("ts16v1.2"), so these eight bytes
        # are ASCII. Only fall back to the hex string when that does not hold.
        self.firmware = ""
        if fw:
            text = "".join(chr(b) for b in fw if 32 <= b < 127).strip()
            self.firmware = text if len(text) >= 3 else fw.hex()
        log("found %s (id %d, internally %s), firmware %s, %s, factors %s, zero points %s"
            % (self.name, self.device_id, self.ctype, self.firmware or "?",
               "INA238" if self.ina == 2 else "INA226", self.sf, self.offsets))

    def _channel_current(self, b, k):
        raw = b[2 * k] * 256 + b[2 * k + 1]
        return max(0.0, (raw - self.offsets[k]) * self.sf[k])

    def read(self, with_aux=True):
        b = self._ask(bytes([0xFE, 0xD0]), self.block_len)
        if len(b) != self.block_len:
            return None
        can_temp = None
        aux_ok = None
        if with_aux:
            # Auxiliary block: byte 0 is the CAN temperature sensor, -101 = no signal
            aux = self._ask(bytes([0xFE, 0xCF]), 4, 0.5)
            aux_ok = len(aux) == 4
            if aux_ok:
                v = signed(aux[0])
                can_temp = None if v == CAN_TEMP_NO_SIGNAL else v
        status = b[21]
        active = bool(status & 0x01)           # bit 0: converter is converting
        blocked = bool(status & 0x20)          # bit 5: disabled through pin 1
        channels = [round(self._channel_current(b, k), 2) for k in range(3)]
        # The total is the sum of the published channels, so that they add up.
        current = round(sum(channels), 2) if active else 0.0
        v_raw = b[10] * 256 + b[11]
        v_out = v_raw * self.spfactor if self.ctype in SPFACTOR_VOUT \
            else v_raw / 1024.0 * 2.0 / VOUT_DIVIDER
        v_in = (b[12] * 256 + b[13]) / 1024.0 * 2.0 / self.vin_divider
        problem = implausible(v_in, v_out, channels if active else ())
        if problem:
            log("implausible block, counted as no answer (%s): %s" % (problem, b.hex()))
            return None
        return {"v_in": round(v_in, 2),
                "v_out": round(v_out, 2),
                "current": current,
                "power": round(v_out * current, 1),
                "channels": channels,
                "active": active,
                "blocked": blocked,
                "status": status,
                # Labels as in TSConfig: byte 19 "Temperature board",
                # bytes 18 and 20 "Temperature mosfet", aux block CAN sensor
                "t_board": signed(b[19]),
                "t_mosfet1": signed(b[18]),
                "t_mosfet2": signed(b[20]),
                "t_can": can_temp,
                "aux_ok": aux_ok}


# SettingsDevice is created in main(), before the Driver that wants its
# change events exists.
_setting_listeners = []


def _setting_changed(setting, old, new):
    for listener in _setting_listeners:
        listener(setting, old, new)


def open_settings(bus):
    """SettingsDevice with everything this driver keeps across restarts.

    The device instance, the energy counter, the switch for the temperature
    devices and the converter's port all live here. Up to v1.20 a settings
    service that was not up within ten seconds meant running with instance
    40 and a counter of 0 until the next restart, possibly for days. Now it
    is fatal: the pause in __main__ and a restart by daemontools cure a slow
    boot.
    """
    from settingsdevice import SettingsDevice
    base = "/Settings/Devices/%s/" % SETTINGS_NAME
    return SettingsDevice(bus, {
        "instance": [base + "ClassAndVrmInstance",
                     "%s:%d" % (SERVICE_CLASS, FALLBACK_INSTANCE), 0, 0],
        "energy": [base + "EnergyOut", 0.0, 0, 0],
        "septemp": [base + "SeparateTempSensors", 0, 0, 1],
        "port": [base + "Port", "", 0, 0]},
        eventCallback=_setting_changed, timeout=10)


def device_instance(settings):
    """The VRM instance from the settings, so that it stays stable.

    Earlier versions of this driver registered as dcdc; that class is migrated
    to alternator here, otherwise VRM keeps filing the device under the old
    class. A value that does not read as <class>:<number> is left alone -
    writing over it would throw away an instance somebody set - and 40 is used
    for this run. A failed migration costs the migration, not the settings.
    """
    stored = settings["instance"]
    cls, sep, num = str(stored).partition(":")
    if not sep or not num.isdigit():
        log("instance setting %r not understood, using %d for this run"
            % (stored, FALLBACK_INSTANCE))
        return FALLBACK_INSTANCE
    instance = int(num)
    if cls == "dcdc":
        try:
            settings["instance"] = "%s:%d" % (SERVICE_CLASS, instance)
            log("device class migrated from dcdc to %s" % SERVICE_CLASS)
        except Exception as e:
            log("device class migration failed (%r), instance %d kept" % (e, instance))
    elif cls != SERVICE_CLASS:
        log("instance setting has class %s, instance %d used as it is" % (cls, instance))
    return instance


def stored_energy(settings):
    """The saved energy counter in kWh, or None when it cannot be trusted."""
    try:
        value = float(settings["energy"])
    except Exception:
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def stored_port(settings):
    """The by-id path confirmed as the converter last time, or None."""
    try:
        port = str(settings["port"] or "")
    except Exception:
        return None
    return port if port.startswith("/dev/") else None


def temp_instances(bus):
    """Device instances of the separate temperature devices, from the settings.

    Up to v1.20 they were fixed at 41-44, past localsettings, and a collision
    could not be resolved the way the ReadMe describes for the main device.
    Returns the instances and the SettingsDevice, which has to be kept alive.
    """
    from settingsdevice import SettingsDevice
    spec = {}
    for key, _field, _label, inst in TEMP_SENSORS:
        spec[key] = ["/Settings/Devices/%s_%s/ClassAndVrmInstance"
                     % (SETTINGS_NAME, key.lower()), "temperature:%d" % inst, 0, 0]
    s = SettingsDevice(bus, spec, eventCallback=None, timeout=10)
    result = {}
    for key, _field, _label, inst in TEMP_SENSORS:
        _cls, sep, num = str(s[key]).partition(":")
        result[key] = int(num) if sep and num.isdigit() else inst
    return result, s


def load_alarm_state():
    """The alarm level of the previous process, if it ended a moment ago.

    A restart used to start the alarm at 0: at 80-84 °C an alarm fell back to
    a warning, although the hysteresis says it stays.
    """
    try:
        with open(os.path.join(STATE_DIR, "alarm")) as f:
            level, stamp = f.read().split()
        level, stamp = int(level), float(stamp)
    except (OSError, ValueError):
        return 0
    if level in (1, 2) and 0 <= time.monotonic() - stamp <= ALARM_STATE_MAX_AGE:
        return level
    return 0


def save_alarm_state(level):
    path = os.path.join(STATE_DIR, "alarm")
    try:
        if level:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(path + ".new", "w") as f:
                f.write("%d %.1f\n" % (level, time.monotonic()))
            os.rename(path + ".new", path)
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


class Driver(object):
    def __init__(self, port, bus, settings, explicit=False):
        self.port = port
        self.bus = bus
        self.settings = settings
        self.explicit = explicit
        self.last_status = None
        self.conv = Converter(port)
        if not explicit:
            self._remember_port()
        instance = device_instance(settings)
        energy = stored_energy(settings)
        self.energy_known = energy is not None
        if not self.energy_known:
            log("stored energy counter unreadable - not published and not "
                "overwritten in this run")
        self.energy = energy if energy is not None else 0.0
        self.energy_saved = self.energy
        self.last_tick = None
        self.last_save = time.monotonic()
        self.temp_alarm = load_alarm_state()
        self.alarm_streak = 0
        self.read_errors = 0
        self.polls = 0
        self.aux_misses = 0
        self.septemp = self._separate_sensors()
        svcname = "com.victronenergy.%s.tsbb_%s" % (
            SERVICE_CLASS, os.path.basename(os.path.realpath(port)))
        try:
            self.svc = VeDbusService(svcname, bus=bus, register=False)
            deferred = True
        except TypeError:                      # older velib_python
            self.svc = VeDbusService(svcname, bus=bus)
            deferred = False

        s = self.svc
        s.add_path("/Mgmt/ProcessName", os.path.basename(__file__))
        s.add_path("/Mgmt/ProcessVersion", VERSION)
        # The "Connection" row on the device page is the only field both GUI
        # versions render as free text, so the driver version goes there next to
        # the port name. gui-v2 has no package manager to show it instead.
        s.add_path("/Mgmt/Connection", "%s (TsBuckBoost v%s)"
                   % (os.path.basename(os.path.realpath(port)), VERSION))
        s.add_path("/DeviceInstance", instance)
        s.add_path("/ProductId", 0xFFFF)
        s.add_path("/ProductName", "Buck-Boost %s" % self.conv.name)
        s.add_path("/FirmwareVersion", self.conv.firmware)
        s.add_path("/Serial", "%s-%d" % (self.conv.ctype, self.conv.device_id))
        s.add_path("/Connected", 1)
        # /Mode mirrors the enable input on pin 1: 1 = enabled, 4 = disabled.
        # Read-only — the converter cannot be switched over this interface,
        # only through the hardware input on pin 1.
        s.add_path("/Mode", 1)
        s.add_path("/State", 0)                # 0 = off, 3 = bulk
        s.add_path("/DeviceOffReason", 0)      # bitmask, 0x08 = pin 1 disables
        s.add_path("/Alarms/HighTemperature", self.temp_alarm)  # 0 ok, 1 warning, 2 alarm
        s.add_path("/History/EnergyOut", round(self.energy, 2) if self.energy_known else None)
        for p in ("/Dc/0/Voltage", "/Dc/0/Current", "/Dc/0/Power",
                  "/Dc/In/V", "/Dc/1/Voltage",
                  # everything else the converter offers — the same values
                  # TSConfig shows in its monitor window
                  "/Temperature/Board", "/Temperature/Mosfet1",
                  "/Temperature/Mosfet2", "/Temperature/CanSensor",
                  "/Current/Channel1", "/Current/Channel2", "/Current/Channel3",
                  "/StatusByte", "/Status/Converting", "/Status/BlockedByPin1"):
            s.add_path(p, None)
        if deferred:
            s.register()
        log("registered as %s, instance %d" % (svcname, instance))

        self.temp_services = {}
        self.temp_buses = []
        self.temp_settings = None
        self.temp_instances = {}
        self.can_tried = False
        if self.septemp:
            self._create_temp_services()
        else:
            log("separate temperature devices off (SeparateTempSensors = 0)")

        _setting_listeners.append(self._setting_changed)
        self._catch_sigterm()

    def _remember_port(self):
        try:
            if stored_port(self.settings) != self.port:
                self.settings["port"] = self.port
                log("%s remembered as the converter's port" % self.port)
        except Exception as e:
            log("port not remembered: %r" % (e,))

    def _separate_sensors(self):
        try:
            return int(self.settings["septemp"]) == 1
        except Exception:
            return False

    def _create_temp_services(self):
        try:
            self.temp_instances, self.temp_settings = temp_instances(self.bus)
        except Exception as e:
            log("temperature device instances not in the settings (%r), using 41-44" % (e,))
            self.temp_instances = dict((key, inst) for key, _f, _l, inst in TEMP_SENSORS)
        first = None
        try:
            first = self.conv.read()
        except Exception:
            pass
        for key, _field, label, _inst in TEMP_SENSORS:
            # only create the CAN sensor when one actually answers
            if key == "CanSensor" and (first is None or first.get("t_can") is None):
                continue
            self._add_temp_service(key, label)
        if self.temp_services:
            log("additional temperature devices: %s" % ", ".join(sorted(self.temp_services)))

    def _add_temp_service(self, key, label):
        try:
            self.temp_services[key] = self._temp_service(key, label, self.temp_instances[key])
            return True
        except Exception as e:
            log("temperature device %s not created: %s" % (key, e))
            return False

    def _temp_service(self, key, label, instance):
        name = "com.victronenergy.temperature.tsbb_%s" % key.lower()
        bus = private_bus()
        try:
            try:
                svc = VeDbusService(name, bus=bus, register=False)
                deferred = True
            except TypeError:
                svc = VeDbusService(name, bus=bus)
                deferred = False
            svc.add_path("/Mgmt/ProcessName", os.path.basename(__file__))
            svc.add_path("/Mgmt/ProcessVersion", VERSION)
            svc.add_path("/Mgmt/Connection", "%s (TsBuckBoost v%s)"
                         % (os.path.basename(os.path.realpath(self.port)), VERSION))
            svc.add_path("/DeviceInstance", instance)
            svc.add_path("/ProductId", 0xFFFF)
            svc.add_path("/ProductName", "Buck-Boost %s" % label)
            svc.add_path("/CustomName", "Buck-Boost %s" % label)
            svc.add_path("/Connected", 1)
            # 2 = generic. Never 0: systemcalc offers type 0 (battery) under
            # DVCC as the battery temperature source.
            svc.add_path("/TemperatureType", 2)
            svc.add_path("/Status", 0)             # 0 = ok, 1 = disconnected
            svc.add_path("/Temperature", None)
            if deferred:
                svc.register()
        except Exception:
            # a connection that serves nothing would stay open for the whole run
            try:
                bus.close()
            except Exception:
                pass
            raise
        self.temp_buses.append(bus)        # keep a reference, or Python collects it
        return svc

    def _catch_sigterm(self):
        """svc -t and svc -d end the driver with SIGTERM. Python's default ends
        the process on the spot, and the energy since the last save was lost:
        up to five minutes on every restart from the Node-RED flow, a package
        update or the console."""
        if hasattr(GLib, "unix_signal_add"):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self._on_sigterm)
        else:
            signal.signal(signal.SIGTERM, lambda signum, frame: self._on_sigterm())

    def _on_sigterm(self):
        self._exit(0, "SIGTERM - stopping")
        return False

    def _setting_changed(self, setting, old, new):
        # Runs inside a D-Bus signal handler, where ending the process is not
        # reliable; the restart is handed to the main loop.
        if setting == "septemp":
            try:
                wanted = int(new) == 1
            except (TypeError, ValueError):
                return
            if wanted != self.septemp:
                GLib.idle_add(self._restart_for_septemp)
        elif setting == "energy":
            self._energy_changed(new)

    def _restart_for_septemp(self):
        # The temperature devices are created at start, so a new value of the
        # switch takes a restart - whoever wrote it: the flow, the console, VRM.
        self._exit(0, "SeparateTempSensors changed - restarting to apply it")
        return False

    def _energy_changed(self, new):
        """EnergyOut was written from outside - a reset from the console, say.
        Our own writes come back here as well and are known by their value."""
        try:
            value = float(new)
        except (TypeError, ValueError):
            return
        if not math.isfinite(value) or value < 0 or abs(value - self.energy_saved) < 1e-6:
            return
        log("energy counter set to %.3f kWh from outside" % value)
        self.energy = self.energy_saved = value
        self.energy_known = True
        self.svc["/History/EnergyOut"] = round(value, 2)

    def _save_energy(self, quiet=True):
        """Write the counter to localsettings - never to the converter - if it
        has changed. A failed write is tried again after ENERGY_RETRY seconds
        rather than after the full interval."""
        if not self.energy_known:
            return
        now = time.monotonic()
        if round(self.energy, 3) == round(self.energy_saved, 3):
            self.last_save = now
            return
        try:
            self.settings["energy"] = self.energy
        except Exception as e:
            log("energy counter not stored (%.3f kWh, stored %.3f kWh): %r"
                % (self.energy, self.energy_saved, e))
            self.last_save = now - ENERGY_SAVE_INTERVAL + ENERGY_RETRY
            return
        self.energy_saved = self.energy
        self.last_save = now
        if not quiet:
            log("energy counter stored: %.3f kWh" % self.energy)

    def _exit(self, code, reason):
        """Log why, save the energy counter and end the process; daemontools
        starts it again."""
        log(reason)
        try:
            self._save_energy(quiet=False)
        except Exception as e:
            log("energy counter not stored: %r" % (e,))
        exit_process(code)

    def update(self):
        """GLib timer callback. Anything that escapes here would make GLib
        drop the timer silently and leave a process that looks alive but never
        updates again - so every failure ends the process instead, and
        daemontools restarts it."""
        try:
            return self._update()
        except Exception as e:
            self._exit(1, "update failed: %r - restarting the service" % (e,))

    def _mark_disconnected(self):
        s = self.svc
        s["/Connected"] = 0
        s["/State"] = 0
        s["/Dc/0/Current"] = 0
        s["/Dc/0/Power"] = 0
        # Old readings must not linger on the bus as if they were current. The
        # temperature alarm stays: silence is no proof the converter cooled down.
        for p in ("/Dc/0/Voltage", "/Dc/In/V", "/Dc/1/Voltage",
                  "/Temperature/Board", "/Temperature/Mosfet1",
                  "/Temperature/Mosfet2", "/Temperature/CanSensor",
                  "/Current/Channel1", "/Current/Channel2", "/Current/Channel3",
                  "/StatusByte", "/Status/Converting", "/Status/BlockedByPin1",
                  "/Mode", "/DeviceOffReason"):
            s[p] = None
        for svc in self.temp_services.values():
            svc["/Temperature"] = None
            svc["/Status"] = 1
            svc["/Connected"] = 0
        self.last_status = None
        # The next reading starts a new energy interval instead of booking the gap.
        self.last_tick = None

    def _no_answer(self):
        self.read_errors += 1
        self._mark_disconnected()
        if not os.path.exists(self.port):
            self._exit(1, "port disappeared - restarting the service")
        # The most likely reason for silence is not the converter but
        # another driver that has handed this port back to serial-starter
        # while looking for its own hardware - after which the Venus probe
        # services are on the line again. Taking it back costs one call
        # and is cheaper than the restart below. A port given as an argument
        # is the tester's business: serial-starter is not touched then.
        if self.read_errors == 2 and not self.explicit:
            release_from_serial_starter(self.port, timeout=5, settle=0)
        if self.read_errors >= MAX_READ_ERRORS:
            # The by-id link may still exist while our descriptor is dead
            # (USB re-enumeration). Reopening is the only cure.
            self._exit(1, "%d polls without an answer - restarting the service"
                       % self.read_errors)
        return True

    def _alarm_level(self, hottest):
        """Two-level alarm with hysteresis. A level is entered at its threshold
        after ALARM_CONFIRM_POLLS readings in a row, and left again
        TEMP_HYSTERESIS below it.
          0 -> 1 at 75, 1 -> 0 below 70;  1 -> 2 at 85, 2 -> 1 below 80"""
        target = 2 if hottest >= TEMP_ALARM else 1 if hottest >= TEMP_WARNING else 0
        level = self.temp_alarm
        if target > level:
            self.alarm_streak += 1
            if self.alarm_streak >= ALARM_CONFIRM_POLLS:
                self.alarm_streak = 0
                return target
            return level
        self.alarm_streak = 0
        if level == 2 and hottest < TEMP_ALARM - TEMP_HYSTERESIS:
            level = 1
        if level == 1 and hottest < TEMP_WARNING - TEMP_HYSTERESIS:
            level = 0
        return level

    def _update(self):
        self.polls += 1
        with_aux = self.aux_misses < AUX_MISSES or self.polls % AUX_RETRY_POLLS == 0
        try:
            d = self.conv.read(with_aux)
        except LineChanged as e:
            self._exit(1, "%s - restarting, which opens the port at 9600 again" % e)
        except Exception as e:
            log("read error: %s" % e)
            d = None
        if d is None:
            return self._no_answer()
        if d["aux_ok"] is not None:
            if d["aux_ok"]:
                self.aux_misses = 0
            else:
                self.aux_misses += 1
                if self.aux_misses == AUX_MISSES:
                    log("no answer to the auxiliary block (FE CF), asking only "
                        "every %d polls" % AUX_RETRY_POLLS)
        self.read_errors = 0
        s = self.svc
        s["/Connected"] = 1
        s["/Dc/0/Voltage"] = d["v_out"]
        s["/Dc/0/Current"] = d["current"]
        s["/Dc/0/Power"] = d["power"]
        s["/Dc/In/V"] = d["v_in"]
        s["/Dc/1/Voltage"] = d["v_in"]
        # No /Dc/0/Temperature, on purpose: Venus reads that path as battery
        # temperature. systemcalc offers every alternator service with a valid
        # /Dc/0/Temperature under DVCC as the battery temperature source
        # (dbus-systemcalc-py, delegates/batterysense.py), and chosen there it
        # would hand MOSFET heat to every charger. Up to v1.20 the hotter
        # MOSFET went there for the temperature line of the GX device page;
        # that line is gone with it. The separate temperature devices carry
        # /TemperatureType 2, which systemcalc does not offer.
        hottest = max(d["t_mosfet1"], d["t_mosfet2"])
        s["/Temperature/Board"] = d["t_board"]
        s["/Temperature/Mosfet1"] = d["t_mosfet1"]
        s["/Temperature/Mosfet2"] = d["t_mosfet2"]
        s["/Temperature/CanSensor"] = d["t_can"]
        for k in range(3):
            s["/Current/Channel%d" % (k + 1)] = d["channels"][k] if d["active"] else 0
        self._count_energy(d)

        self.temp_alarm = self._alarm_level(hottest)
        s["/Alarms/HighTemperature"] = self.temp_alarm
        save_alarm_state(self.temp_alarm)

        self._update_temp_services(d)

        s["/StatusByte"] = d["status"]
        s["/Status/Converting"] = 1 if d["active"] else 0
        s["/Status/BlockedByPin1"] = 1 if d["blocked"] else 0
        s["/State"] = 3 if d["active"] else 0
        s["/Mode"] = 4 if d["blocked"] else 1
        s["/DeviceOffReason"] = OFF_REASON_REMOTE_CONNECTOR if d["blocked"] else 0
        if d["status"] != self.last_status:
            log("status 0x%02X: %s" % (d["status"], describe(d["status"])))
            self.last_status = d["status"]
        return True

    def _count_energy(self, d):
        now = time.monotonic()
        if self.energy_known and d["active"] and self.last_tick is not None:
            dt = now - self.last_tick
            if 0 < dt <= MAX_ENERGY_DT:
                self.energy += d["power"] * dt / 3600000.0   # W * s -> kWh
        self.last_tick = now
        if self.energy_known:
            self.svc["/History/EnergyOut"] = round(self.energy, 2)
            if now - self.last_save > ENERGY_SAVE_INTERVAL:
                self._save_energy()

    def _update_temp_services(self, d):
        if (self.septemp and not self.can_tried and d["t_can"] is not None
                and "CanSensor" not in self.temp_services):
            # a TS Temp sensor that did not answer at start
            self.can_tried = True
            label = [lb for key, _f, lb, _i in TEMP_SENSORS if key == "CanSensor"][0]
            if self._add_temp_service("CanSensor", label):
                log("CAN temperature sensor answers now - device created")
        for key, field, _label, _inst in TEMP_SENSORS:
            svc = self.temp_services.get(key)
            if svc is None:
                continue
            value = d.get(field)
            svc["/Temperature"] = value
            svc["/Status"] = 0 if value is not None else 1
            svc["/Connected"] = 1 if value is not None else 0


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    log("dbus-tsbb %s starting" % VERSION)
    bus = dbus.SystemBus()
    settings = open_settings(bus)
    if len(sys.argv) > 1:
        port = sys.argv[1]      # explicit port: no probing, no stop-tty, not remembered
        explicit = True
    else:
        port = search(settings)
        explicit = False
    log("using port %s" % port)
    driver = Driver(port, bus, settings, explicit)
    driver.update()
    GLib.timeout_add(POLL_MS, driver.update)
    GLib.MainLoop().run()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("aborted: %s" % exc)
        time.sleep(10)                         # do not hammer daemontools
        sys.exit(1)
