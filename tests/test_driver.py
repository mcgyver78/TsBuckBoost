"""Tests for dbus-tsbb.py without Venus OS and without hardware.

serial, dbus, gi, vedbus and settingsdevice are replaced by small fakes, and
the converter is a scripted device behind a fake serial port. Time is a fake
clock, so waiting costs nothing. The line-settings check runs against a real
pseudo-terminal. Nothing here opens a serial port or talks to D-Bus.
"""
import importlib.util
import os
import pty
import shutil
import signal
import sys
import tempfile
import termios
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVER = os.path.join(ROOT, "dbus-tsbb.py")
CRTSCTS = getattr(termios, "CRTSCTS", 0)
BLOCK_LEN = 22
NMEA = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n"


class RunAway(BaseException):
    """The fake clock went past a simulated day: something waits forever.
    BaseException, so that no 'except Exception' in the driver hides it."""


class Exited(BaseException):
    """exit_process() under test: ends the test's call chain like os._exit
    would end the process, but is not caught by 'except Exception'."""

    def __init__(self, code):
        BaseException.__init__(self, code)
        self.code = code


def set_line(fd, speed=termios.B9600, parity=False, rtscts=False):
    """Put a tty into the state pyserial leaves it in (or a foreign one)."""
    attrs = termios.tcgetattr(fd)
    attrs[0] &= ~(termios.IXON | termios.IXOFF | termios.ISTRIP | termios.ICRNL
                  | termios.INLCR | termios.IGNCR)
    attrs[1] &= ~termios.OPOST
    cflag = attrs[2] & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB | CRTSCTS)
    cflag |= termios.CS8 | termios.CREAD | termios.CLOCAL
    if parity:
        cflag |= termios.PARENB
    if rtscts:
        cflag |= CRTSCTS
    attrs[2] = cflag
    attrs[3] &= ~(termios.ICANON | termios.ECHO | termios.ISIG | termios.IEXTEN)
    attrs[4] = attrs[5] = speed
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def live_block(v_out=26.9, v_in=13.5, amps=(9.0, 9.0, 9.0), temps=(40, 45, 47),
               status=0x01):
    """A 22-byte FE D0 answer of a TS800C5 with the calibration of FakeConverter:
    factors 0.05 A per count, zero points 10, INA238 (0.003125 V per count)."""
    b = bytearray(BLOCK_LEN)
    for k, a in enumerate(amps):
        raw = int(round(a / 0.05)) + 10
        b[2 * k], b[2 * k + 1] = raw >> 8, raw & 0xFF
    vr = int(round(v_out / 0.003125))
    b[10], b[11] = vr >> 8, vr & 0xFF
    ir = int(round(v_in * 0.0636 / 2.0 * 1024))
    b[12], b[13] = ir >> 8, ir & 0xFF
    b[19], b[18], b[20] = (t & 0xFF for t in temps)
    b[21] = status
    return bytes(b)


class FakeConverter(object):
    """Answers the read commands the way the converter does: exactly the
    requested bytes, nothing unasked."""

    def __init__(self, dev_id=113):
        cal = bytearray(64)
        cal[41:44] = bytes([10, 10, 10])
        self.memory = {(0x1F, 0xF2): bytes([dev_id]),
                       (0x1F, 0xF5): bytes([2]),
                       (0x1F, 0xE0): bytes([50, 50, 50] + [0] * 13),
                       (0x1F, 0x2A): bytes(cal),
                       (0x00, 0xD0): b"ts16v1.2"}
        self.cal_answers = {}         # request length -> bytes that arrive
        self.block = live_block()
        self.aux = bytes([(-101) & 0xFF, 0, 0, 0])     # no CAN sensor
        self.answer_aux = True
        self.silent = False
        self.extra = b""              # sent after the id
        self.broken = False

    def respond(self, frame):
        if self.silent:
            return b""
        if frame[:2] == b"\xfe\x11":
            page, addr, length = frame[2], frame[3], frame[4]
            data = self.memory.get((page, addr), b"")[:length]
            if (page, addr) == (0x1F, 0x2A) and length in self.cal_answers:
                data = data[:self.cal_answers[length]]
            if (page, addr) == (0x1F, 0xF2):
                data += self.extra
            return data
        if frame == b"\xfe\xd0":
            return self.block
        if frame == b"\xfe\xcf":
            return self.aux if self.answer_aux else b""
        return b""

    def talk(self, n):
        return b""


class Talker(FakeConverter):
    """A foreign device that sends on its own, like a GPS."""

    def __init__(self):
        FakeConverter.__init__(self)
        self.pos = 0

    def respond(self, frame):
        return b""

    def talk(self, n):
        out = bytes(NMEA[(self.pos + i) % len(NMEA)] for i in range(n))
        self.pos += n
        return out


class Streamer(FakeConverter):
    """Quiet until asked, then a burst that starts with a valid id."""

    def respond(self, frame):
        return b"q" + NMEA * 3


class World(object):
    """Everything the fakes share within one test."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.now = 1000.0
        self.sleep_hooks = []
        self.devices = {}
        self.present = []
        self.frames = []              # (port, frame) in the order written
        self.events = []
        self.logs = []
        self.store = {}               # settings path -> value
        self.writes = []
        self.fail_set = {}
        self.settings_unavailable = False
        self.settings_devices = []
        self.services = []
        self.fail_service = None
        self.stop_tty_rc = 0
        self.apply_termios = False
        self.idle = []
        self.signals = {}
        self.master, self.slave = pty.openpty()
        set_line(self.slave)

    def close(self):
        os.close(self.master)
        os.close(self.slave)

    # the clock
    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)
        if self.now - 1000.0 > 86400:
            raise RunAway("fake clock ran for more than a day - endless wait")
        for hook in list(self.sleep_hooks):
            hook()


def make_fakes(world):
    """sys.modules entries for everything the driver imports from Venus."""

    class SerialException(IOError):
        pass

    class FakeSerial(object):
        def __init__(self, port, baudrate=9600, bytesize=8, parity="N", stopbits=1,
                     timeout=None, exclusive=None, **kw):
            device = world.devices.get(port)
            if device is None:
                raise SerialException("could not open port %s" % port)
            self.port = port
            self.device = device
            self.timeout = timeout
            self.write_timeout = None
            self.rx = bytearray()
            self.dtr = self.rts = False
            self.fd = world.slave
            self.own_fd = None
            if world.apply_termios:
                # what pyserial does on open: 9600 8N1 raw, for the whole tty
                self.own_fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                set_line(self.own_fd)
                self.fd = self.own_fd
            world.events.append(("open", port))

        def fileno(self):
            return self.fd

        def write(self, data):
            data = bytes(data)
            world.events.append(("write", self.port, data))
            if self.device.broken:
                raise OSError(5, "Input/output error")
            world.frames.append((self.port, data))
            self.rx += self.device.respond(data)
            return len(data)

        def read(self, n=1):
            if not self.rx:
                self.rx += self.device.talk(n)
            if not self.rx:
                world.sleep(self.timeout or 0)
                return b""
            out = bytes(self.rx[:n])
            del self.rx[:n]
            return out

        @property
        def in_waiting(self):
            self.rx += self.device.talk(8)
            return len(self.rx)

        def reset_input_buffer(self):
            self.rx = bytearray()

        def flush(self):
            pass

        def close(self):
            if self.own_fd is not None:
                os.close(self.own_fd)
                self.own_fd = None

    serial_mod = types.ModuleType("serial")
    serial_mod.Serial = FakeSerial
    serial_mod.SerialException = SerialException

    class Bus(object):
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    dbus_mod = types.ModuleType("dbus")
    dbus_mod.SystemBus = lambda private=False: Bus()
    dbus_mod.bus = types.SimpleNamespace(BusConnection=lambda addr: Bus())
    mainloop = types.ModuleType("dbus.mainloop")
    glib_loop = types.ModuleType("dbus.mainloop.glib")
    glib_loop.DBusGMainLoop = lambda set_as_default=False: None
    mainloop.glib = glib_loop
    dbus_mod.mainloop = mainloop

    class GLib(object):
        PRIORITY_HIGH = -100

        @staticmethod
        def idle_add(fn, *args):
            world.idle.append(fn)
            return 1

        @staticmethod
        def unix_signal_add(priority, signum, fn, *args):
            world.signals[signum] = fn
            return 1

        @staticmethod
        def timeout_add(ms, fn, *args):
            return 1

    gi_mod = types.ModuleType("gi")
    repo = types.ModuleType("gi.repository")
    repo.GLib = GLib
    gi_mod.repository = repo

    class VeDbusService(object):
        def __init__(self, name, bus=None, register=None):
            if world.fail_service and name.endswith(world.fail_service):
                raise RuntimeError("cannot register %s" % name)
            self.name = name
            self.bus = bus
            self.paths = {}
            self.registered = False
            world.services.append(self)

        def add_path(self, path, value, **kw):
            self.paths[path] = value

        def register(self):
            self.registered = True

        def __getitem__(self, path):
            return self.paths[path]

        def __setitem__(self, path, value):
            if path not in self.paths:
                raise KeyError(path)
            self.paths[path] = value

    vedbus = types.ModuleType("vedbus")
    vedbus.VeDbusService = VeDbusService

    class SettingsDevice(object):
        def __init__(self, bus, supportedSettings, eventCallback, name=None, timeout=0):
            if world.settings_unavailable:
                raise Exception("The settings service com.victronenergy.settings "
                                "does not exist!")
            self.callback = eventCallback
            self.paths = dict((k, v[0]) for k, v in supportedSettings.items())
            self.values = {}
            for key, (path, default, _lo, _hi) in supportedSettings.items():
                world.store.setdefault(path, default)
                self.values[key] = world.store[path]
            world.settings_devices.append(self)

        def __getitem__(self, key):
            return self.values[key]

        def __setitem__(self, key, value):
            if world.fail_set.get(key):
                world.fail_set[key] -= 1
                raise AssertionError("SetValue failed")
            self.values[key] = value
            world.store[self.paths[key]] = value
            world.writes.append((key, value))

        def external(self, key, value):
            """Somebody else writes the setting; localsettings tells us."""
            old = self.values.get(key)
            self.values[key] = value
            world.store[self.paths[key]] = value
            if self.callback:
                self.callback(key, old, value)

    settingsdevice = types.ModuleType("settingsdevice")
    settingsdevice.SettingsDevice = SettingsDevice

    return {"serial": serial_mod, "dbus": dbus_mod, "dbus.mainloop": mainloop,
            "dbus.mainloop.glib": glib_loop, "gi": gi_mod, "gi.repository": repo,
            "vedbus": vedbus, "settingsdevice": settingsdevice}, Bus


def load_driver(world, tmp):
    fakes, bus_class = make_fakes(world)
    saved = dict((name, sys.modules.get(name)) for name in fakes)
    sys.modules.update(fakes)
    try:
        spec = importlib.util.spec_from_file_location("dbus_tsbb_under_test", DRIVER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    # settingsdevice is imported inside functions: keep it reachable
    mod._fake_settingsdevice = fakes["settingsdevice"]

    def exit_process(code):
        raise Exited(code)

    def fake_call(args, timeout=None):
        world.events.append(("stop-tty", args[1]))
        return world.stop_tty_rc

    stop_tty = os.path.join(tmp, "stop-tty.sh")
    open(stop_tty, "w").close()
    mod.time = types.SimpleNamespace(sleep=world.sleep, monotonic=world.monotonic,
                                     time=world.monotonic, strftime=lambda fmt: "00:00:00")
    mod.subprocess = types.SimpleNamespace(call=fake_call)
    mod.exit_process = exit_process
    mod.log = world.logs.append
    mod.STOP_TTY = stop_tty
    mod.STATE_DIR = os.path.join(tmp, "run")
    mod.candidate_ports = lambda: sorted(world.present)
    return mod, bus_class


class DriverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tsbb-test-")
        self.world = World(self.tmp)
        self.mod, self.Bus = load_driver(self.world, self.tmp)
        sys.modules["settingsdevice"] = self.mod._fake_settingsdevice

    def tearDown(self):
        sys.modules.pop("settingsdevice", None)
        self.world.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_port(self, name, device, present=True):
        path = os.path.join(self.tmp, "usb-Silicon_Labs_CP2102N_%s-if00-port0" % name)
        open(path, "w").close()
        self.world.devices[path] = device
        if present:
            self.world.present.append(path)
        return path

    def settings(self):
        return self.mod.open_settings(self.Bus())

    def driver(self, port, explicit=False, settings=None):
        settings = settings or self.settings()
        return self.mod.Driver(port, self.Bus(), settings, explicit)

    def poll(self, drv, n=1, seconds=2.0):
        for _ in range(n):
            self.world.sleep(seconds)
            drv.update()

    def setting(self, name):
        return self.world.store["/Settings/Devices/tsbuckboost/%s" % name]

    def logged(self, text):
        return any(text in line for line in self.world.logs)


class SendGuard(DriverTest):
    def test_a_write_command_is_refused(self):
        conv = FakeConverter()
        port = self.add_port("A", conv)
        ser = self.mod.serial.Serial(port)
        with self.assertRaises(ValueError):
            self.mod.send_read(ser, bytes([0xFE, 0x02, 0x1F, 0xF2, 0x01]))
        self.assertEqual(self.world.frames, [])

    def test_every_frame_sent_is_a_read_command(self):
        self.add_port("A", Talker())
        silent = FakeConverter()
        silent.silent = True
        self.add_port("B", silent)
        conv = FakeConverter()
        port = self.add_port("C", conv)
        found = self.mod.search(self.settings())
        self.assertEqual(found, port)
        drv = self.driver(found)
        self.poll(drv, 20)
        self.assertTrue(self.world.frames)
        for _port, frame in self.world.frames:
            self.assertEqual(frame[0], 0xFE, frame.hex())
            self.assertIn(frame[1], (0x11, 0xD0, 0xCF), frame.hex())

    def test_the_line_check_follows_the_tty(self):
        ser = types.SimpleNamespace(fileno=lambda: self.world.slave, port="pty")
        self.assertTrue(self.mod.line_is_ours(ser))
        set_line(self.world.slave, termios.B4800)
        self.assertFalse(self.mod.line_is_ours(ser))
        set_line(self.world.slave, parity=True)
        self.assertFalse(self.mod.line_is_ours(ser))
        set_line(self.world.slave, rtscts=True)
        self.assertFalse(self.mod.line_is_ours(ser))
        set_line(self.world.slave)
        self.assertTrue(self.mod.line_is_ours(ser))

    def test_nothing_is_sent_once_the_line_changed(self):
        port = self.add_port("A", FakeConverter())
        drv = self.driver(port)
        self.poll(drv, 3)
        sent = len(self.world.frames)
        set_line(self.world.slave, termios.B4800)     # a probe service took over
        with self.assertRaises(Exited) as caught:
            self.poll(drv)
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(len(self.world.frames), sent)


class Probe(DriverTest):
    def test_the_converter_is_found(self):
        port = self.add_port("A", FakeConverter())
        self.assertEqual(self.mod.probe_identity(port), 113)

    def test_a_talking_device_gets_nothing_written(self):
        port = self.add_port("A", Talker())
        self.assertIsNone(self.mod.probe_identity(port))
        self.assertEqual(self.world.frames, [])

    def test_a_stream_after_the_question_is_no_converter(self):
        port = self.add_port("A", Streamer())
        self.assertIsNone(self.mod.probe_identity(port))

    def test_a_short_tail_after_the_id_is_taken_and_logged(self):
        # One byte is what the protocol says, not what was measured on the
        # converter; a tail must not cost the converter its discovery.
        conv = FakeConverter()
        conv.extra = b"\x00"
        port = self.add_port("A", conv)
        self.assertEqual(self.mod.probe_identity(port), 113)
        self.assertTrue(self.logged("more than its id: 7100 / 7100"))

    def test_an_old_short_block_type_is_left_with_serial_starter(self):
        self.add_port("A", FakeConverter(dev_id=63))       # TS400
        self.assertIsNone(self.mod.find_port())
        self.assertNotIn("stop-tty", [e[0] for e in self.world.events])
        self.assertTrue(self.logged("model not supported"))

    def test_an_io_error_on_one_port_does_not_end_the_search(self):
        broken = FakeConverter()
        broken.broken = True
        self.add_port("A", broken)
        port = self.add_port("B", FakeConverter())
        self.assertEqual(self.mod.find_port(), port)

    def test_line_settings_are_put_back_after_a_probe(self):
        name = os.ttyname(self.world.slave)
        self.world.devices[name] = Talker()
        self.world.apply_termios = True
        set_line(self.world.slave, termios.B4800)          # a GPS service at 4800
        self.mod.probe_identity(name)
        self.assertEqual(termios.tcgetattr(self.world.slave)[4], termios.B4800)


class Search(DriverTest):
    def test_the_known_port_is_asked_alone(self):
        off = FakeConverter()
        off.silent = True
        known = self.add_port("A", off)
        other = self.add_port("B", FakeConverter())
        self.assertIsNone(self.mod.find_port(known))
        self.assertNotIn(("open", other), self.world.events)

    def test_all_ports_are_asked_when_the_known_one_is_gone(self):
        gone = os.path.join(self.tmp, "usb-Silicon_Labs_CP2102N_Z-if00-port0")
        port = self.add_port("B", FakeConverter())
        self.assertEqual(self.mod.find_port(gone), port)

    def test_the_known_port_is_released_before_it_is_asked(self):
        known = self.add_port("A", FakeConverter())
        self.assertEqual(self.mod.find_port(known), known)
        mine = [e for e in self.world.events
                if e[0] == "stop-tty" or (len(e) > 1 and e[1] == known)]
        self.assertEqual(mine[0], ("stop-tty", os.path.basename(known)))

    def test_the_search_waits_longer_and_wakes_up_for_a_new_port(self):
        start = self.world.now
        port = os.path.join(self.tmp, "usb-Silicon_Labs_CP2102N_A-if00-port0")
        open(port, "w").close()
        self.world.devices[port] = FakeConverter()

        def plug_in():
            if self.world.now - start >= 100 and port not in self.world.present:
                self.world.present.append(port)
        self.world.sleep_hooks.append(plug_in)
        self.assertEqual(self.mod.search(self.settings()), port)
        self.assertTrue(self.logged("next try in 10 s"))
        self.assertTrue(self.logged("next try in 20 s"))
        # the fourth pause is 80 s (70..150 s); the new port ends it early
        self.assertLess(self.world.now - start, 120)

    def test_the_driver_remembers_its_port(self):
        port = self.add_port("A", FakeConverter())
        self.driver(port)
        self.assertEqual(self.setting("Port"), port)

    def test_an_explicit_port_is_neither_remembered_nor_released(self):
        silent = FakeConverter()
        port = self.add_port("A", silent)
        drv = self.driver(port, explicit=True)
        self.assertEqual(self.setting("Port"), "")
        silent.silent = True
        self.poll(drv, 3)
        self.assertNotIn("stop-tty", [e[0] for e in self.world.events])


class Energy(DriverTest):
    def running(self, energy=1.0):
        self.world.store["/Settings/Devices/tsbuckboost/EnergyOut"] = energy
        self.conv = FakeConverter()
        return self.driver(self.add_port("A", self.conv))

    def test_the_counter_is_stored_when_polls_fail(self):
        drv = self.running()
        self.poll(drv, 100)                           # 200 s at ~726 W
        self.assertEqual(self.setting("EnergyOut"), 1.0)
        self.conv.silent = True
        with self.assertRaises(Exited):
            self.poll(drv, 5)
        self.assertGreater(self.setting("EnergyOut"), 1.03)

    def test_the_counter_is_stored_on_sigterm(self):
        drv = self.running()
        self.poll(drv, 50)
        with self.assertRaises(Exited) as caught:
            self.world.signals[signal.SIGTERM]()
        self.assertEqual(caught.exception.code, 0)
        self.assertGreater(self.setting("EnergyOut"), 1.01)

    def test_a_failed_save_is_tried_again_soon(self):
        drv = self.running()
        self.world.fail_set["energy"] = 1
        self.poll(drv, 152)                           # the first save at 300 s fails
        self.assertEqual(self.setting("EnergyOut"), 1.0)
        self.poll(drv, 20)                            # 40 s later
        self.assertGreater(self.setting("EnergyOut"), 1.0)

    def test_an_outage_is_not_counted_as_energy(self):
        drv = self.running(0.0)
        self.poll(drv, 2)
        before = drv.energy
        # one silent poll: about 5 s until the next reading, well inside
        # MAX_ENERGY_DT, so only the reset of the interval keeps it out
        self.conv.silent = True
        self.poll(drv)
        self.conv.silent = False
        self.poll(drv)
        self.assertEqual(drv.energy, before)          # restart of the interval
        self.poll(drv)
        self.assertAlmostEqual(drv.energy - before, 726.3 * 2 / 3600000.0, places=6)

    def test_an_implausible_block_counts_as_no_answer(self):
        drv = self.running(0.0)
        self.poll(drv)
        before = drv.energy
        self.conv.block = bytes([0xFF] * 21 + [0x01])
        self.poll(drv)
        self.assertEqual(drv.energy, before)
        self.assertEqual(drv.svc["/Connected"], 0)
        self.assertEqual(drv.svc["/Alarms/HighTemperature"], 0)
        self.assertTrue(self.logged("implausible block"))

    def test_an_unreadable_counter_is_not_overwritten(self):
        drv = self.running(None)
        self.assertIsNone(drv.svc["/History/EnergyOut"])
        self.poll(drv, 200)
        self.assertIsNone(self.setting("EnergyOut"))
        self.assertNotIn("energy", [k for k, _v in self.world.writes])

    def test_a_reset_from_outside_is_taken_over(self):
        drv = self.running(5.0)
        self.poll(drv, 10)
        drv.settings.external("energy", 0.0)
        self.assertEqual(drv.energy, 0.0)
        self.poll(drv, 160)
        self.assertLess(self.setting("EnergyOut"), 0.1)

    def test_our_own_write_coming_back_changes_nothing(self):
        drv = self.running()
        self.poll(drv, 160)
        stored = self.setting("EnergyOut")
        drv.settings.external("energy", stored)
        self.assertFalse(self.logged("from outside"))


class Alarm(DriverTest):
    def running(self):
        self.conv = FakeConverter()
        return self.driver(self.add_port("A", self.conv))

    def hottest(self, drv, *temps):
        levels = []
        for t in temps:
            self.conv.block = live_block(temps=(40, t, 40))
            self.poll(drv)
            levels.append(drv.svc["/Alarms/HighTemperature"])
        return levels

    def test_one_hot_block_raises_no_alarm(self):
        drv = self.running()
        self.assertEqual(self.hottest(drv, 50, 127, 50, 50), [0, 0, 0, 0])

    def test_levels_need_two_readings_and_leave_with_hysteresis(self):
        drv = self.running()
        self.assertEqual(self.hottest(drv, 76, 76, 86, 86, 82, 79, 72, 69),
                         [0, 1, 1, 2, 2, 1, 1, 0])

    def test_the_alarm_survives_a_restart(self):
        drv = self.running()
        self.assertEqual(self.hottest(drv, 86, 86, 82), [0, 2, 2])
        again = self.driver(self.add_port("B", self.conv))
        self.assertEqual(self.hottest(again, 82), [2])


class Disconnect(DriverTest):
    def test_status_paths_are_invalidated(self):
        conv = FakeConverter()
        drv = self.driver(self.add_port("A", conv))
        self.poll(drv)
        self.assertEqual(drv.svc["/Status/Converting"], 1)
        conv.silent = True
        self.poll(drv)
        for path in ("/StatusByte", "/Status/Converting", "/Status/BlockedByPin1",
                     "/Mode", "/DeviceOffReason", "/Dc/0/Voltage"):
            self.assertIsNone(drv.svc[path], path)


class Settings(DriverTest):
    def test_a_missing_settings_service_is_fatal(self):
        # main() must not carry on without settings; __main__ then pauses and
        # exits, and daemontools tries again
        self.world.settings_unavailable = True
        self.add_port("A", FakeConverter())
        with self.assertRaises(Exception):
            self.mod.main()
        self.assertEqual(self.world.frames, [])

    def test_an_unreadable_instance_is_left_alone(self):
        self.world.store["/Settings/Devices/tsbuckboost/ClassAndVrmInstance"] = None
        s = self.settings()
        self.assertEqual(self.mod.device_instance(s), 40)
        self.assertNotIn("instance", [k for k, _v in self.world.writes])

    def test_dcdc_is_migrated(self):
        self.world.store["/Settings/Devices/tsbuckboost/ClassAndVrmInstance"] = "dcdc:55"
        self.assertEqual(self.mod.device_instance(self.settings()), 55)
        self.assertEqual(self.setting("ClassAndVrmInstance"), "alternator:55")

    def test_a_failed_migration_keeps_the_instance(self):
        self.world.store["/Settings/Devices/tsbuckboost/ClassAndVrmInstance"] = "dcdc:55"
        self.world.fail_set["instance"] = 1
        self.assertEqual(self.mod.device_instance(self.settings()), 55)

    def test_a_changed_switch_restarts_the_driver(self):
        drv = self.driver(self.add_port("A", FakeConverter()))
        self.poll(drv, 10)
        drv.settings.external("septemp", 1)
        self.assertEqual(len(self.world.idle), 1)
        with self.assertRaises(Exited) as caught:
            self.world.idle[0]()
        self.assertEqual(caught.exception.code, 0)

    def test_the_same_switch_value_restarts_nothing(self):
        drv = self.driver(self.add_port("A", FakeConverter()))
        drv.settings.external("septemp", 0)
        self.assertEqual(self.world.idle, [])


class TemperatureDevices(DriverTest):
    def with_devices(self, conv=None):
        self.world.store["/Settings/Devices/tsbuckboost/SeparateTempSensors"] = 1
        self.conv = conv or FakeConverter()
        return self.driver(self.add_port("A", self.conv))

    def service(self, suffix):
        found = [s for s in self.world.services if s.name.endswith(suffix)]
        return found[-1] if found else None

    def test_instances_come_from_the_settings(self):
        self.world.store["/Settings/Devices/tsbuckboost_board/ClassAndVrmInstance"] = \
            "temperature:51"
        self.with_devices()
        self.assertEqual(self.service("tsbb_board").paths["/DeviceInstance"], 51)
        self.assertEqual(self.service("tsbb_mosfet1").paths["/DeviceInstance"], 42)

    def test_a_can_sensor_that_answers_later_gets_its_device(self):
        drv = self.with_devices()
        self.assertIsNone(self.service("tsbb_cansensor"))
        self.conv.aux = bytes([21, 0, 0, 0])
        self.poll(drv)
        self.assertIsNotNone(self.service("tsbb_cansensor"))
        self.assertEqual(self.service("tsbb_cansensor").paths["/Temperature"], 21)

    def test_a_failed_device_closes_its_connection(self):
        self.world.fail_service = "tsbb_mosfet2"
        drv = self.with_devices()
        self.assertNotIn("Mosfet2", drv.temp_services)
        self.assertEqual(len(drv.temp_buses), 2)
        self.assertTrue(all(not bus.closed for bus in drv.temp_buses))

    def test_nothing_is_offered_as_battery_temperature(self):
        # systemcalc's rule for the DVCC temperature source (dbus-systemcalc-py,
        # delegates/batterysense.py, device_added): these classes with a valid
        # /Dc/0/Temperature, temperature services only with /TemperatureType 0.
        # MOSFET heat must never become battery temperature.
        drv = self.with_devices()
        self.conv.aux = bytes([21, 0, 0, 0])
        self.poll(drv, 3)
        classes = ("battery", "vebus", "solarcharger", "inverter", "multi", "alternator")
        seen, offered = set(), []
        for s in self.world.services:
            cls = s.name.split(".")[2]
            seen.add(cls)
            if cls in classes and s.paths.get("/Dc/0/Temperature") is not None:
                offered.append(s.name)
            if cls == "temperature" and s.paths.get("/TemperatureType") == 0:
                offered.append(s.name)
        self.assertEqual(seen, {"alternator", "temperature"})
        self.assertIsNotNone(drv.svc["/Temperature/Mosfet1"])
        self.assertEqual(len(drv.temp_services), 4)
        self.assertEqual(offered, [])


class Calibration(DriverTest):
    def test_the_longest_answer_is_kept(self):
        conv = FakeConverter()
        conv.cal_answers = {0x40: 45, 0x30: 0}
        drv = self.driver(self.add_port("A", conv))
        self.assertEqual(drv.conv.offsets, [10, 10, 10])

    def test_a_short_calibration_is_fatal(self):
        conv = FakeConverter()
        conv.cal_answers = {0x40: 40, 0x30: 0}
        with self.assertRaises(IOError):
            self.driver(self.add_port("A", conv))


class Aux(DriverTest):
    def test_an_unanswered_aux_block_is_asked_less_often(self):
        conv = FakeConverter()
        conv.answer_aux = False
        drv = self.driver(self.add_port("A", conv))
        self.poll(drv, 40)
        asked = [f for _p, f in self.world.frames if f == b"\xfe\xcf"]
        self.assertEqual(len(asked), 4)             # polls 1-3, then poll 30


class StopTty(DriverTest):
    def test_a_failed_stop_tty_is_not_reported_as_released(self):
        port = self.add_port("A", FakeConverter())
        self.world.stop_tty_rc = 1
        self.assertFalse(self.mod.release_from_serial_starter(port))
        self.assertTrue(self.logged("failed with exit code 1"))
        self.assertFalse(self.logged("released"))


if __name__ == "__main__":
    unittest.main()
