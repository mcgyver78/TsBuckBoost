"""Tests for extras/nodered-separate-temp-sensors.json without Node-RED.

The function nodes run in a JavaScript engine (jsc, the JavaScriptCore shell
of macOS) inside a small simulator that routes messages along the wires of
the flow, with a fake exec node and a fake virtual switch. The shell commands
the flow builds run under /bin/sh against stand-ins for dbus, svc and sleep.
Without jsc these tests are skipped, and say so.
"""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "extras", "nodered-separate-temp-sensors.json")
JSC_PATHS = ("/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc",
             "/System/Library/Frameworks/JavaScriptCore.framework/Resources/jsc")
JSC = next((p for p in JSC_PATHS if os.access(p, os.X_OK)), shutil.which("jsc"))

# Runs the flow. Exec jobs are held until complete() is called, so that a
# command can be "running" while the next message arrives, as on the GX.
SIMULATOR = r"""
var NODES = __FLOW__;
var byId = {};
NODES.forEach(function (n) { byId[n.id] = n; });
var NOW = 1700000000000;
Date.now = function () { return NOW; };
function store() {
    var d = {};
    return {get: function (k) { return d[k]; },
            set: function (k, v) { if (v === undefined) { delete d[k]; } else { d[k] = v; } },
            dump: function () { return d; }};
}
var flowStore = store(), globalStore = store(), contexts = {};
var setting = __SETTING__, switchState = __SWITCH__;
var queue = [], jobs = [], commands = [], statuses = [], warnings = [];
function nodeApi(n) {
    return {id: n.id, status: function (s) { statuses.push([n.id, s]); },
            warn: function (w) { warnings.push([n.id, String(w)]); },
            send: function (m) { send(n.id, m); }};
}
function ctx(n) { return contexts[n.id] || (contexts[n.id] = store()); }
function init() {
    NODES.forEach(function (n) {
        if (n.type === 'function' && n.initialize) {
            new Function('node', 'context', 'flow', 'global', 'env', 'RED', n.initialize)(
                nodeApi(n), ctx(n), flowStore, globalStore, {get: function () {}}, {});
        }
    });
}
function send(id, result) {
    var n = byId[id];
    var outs = Array.isArray(result) ? result : [result];
    for (var i = 0; i < outs.length; i++) {
        if (outs[i] === null || outs[i] === undefined) { continue; }
        (n.wires[i] || []).forEach(function (t) {
            queue.push([t, JSON.parse(JSON.stringify(outs[i]))]);
        });
    }
}
function deliver(id, msg) {
    var n = byId[id];
    if (n.type === 'function') {
        var r = new Function('msg', 'node', 'context', 'flow', 'global', 'env', 'RED', n.func)(
            msg, nodeApi(n), ctx(n), flowStore, globalStore, {get: function () {}}, {});
        if (r !== null && r !== undefined) { send(id, r); }
    } else if (n.type === 'exec') {
        commands.push(String(msg.payload));
        jobs.push([id, msg]);
    } else if (n.type === 'victron-virtual-switch') {
        // input sets the state; a change goes out on the second output
        var v = msg.payload;
        if (v !== switchState) { switchState = v; send(id, [null, {payload: v}]); }
    }
}
function drain() {
    var steps = 0;
    while (queue.length && steps++ < 1000) { var q = queue.shift(); deliver(q[0], q[1]); }
}
// What the command does on the GX, in short: read, or write if different.
function shell(cmd) {
    var out = '';
    if (cmd.indexOf('SetValue') >= 0) {
        var m = cmd.match(/\bV=(\d)/) || cmd.match(/SetValue (\d)/);
        var v = parseInt(m[1], 10);
        if (setting === v) { out = 'unchanged'; } else { setting = v; out = 'switched'; }
    }
    if (cmd.indexOf('RESULT=') >= 0) { out += (out ? '\n' : '') + 'RESULT=' + setting; }
    return out;
}
function complete() {
    var job = jobs.shift();
    var msg = job[1];
    msg.payload = shell(String(msg.payload));
    send(job[0], [msg, null, null]);
    drain();
}
function completeAll(limit) {
    var n = 0;
    while (jobs.length && n++ < limit) { complete(); }
}
function tap(v) {              // somebody taps the switch on the GX display
    switchState = v;
    send('tsbb_vswitch', [null, {payload: v}]);
    drain();
}
function report() {            // what the switch sends after a deploy
    send('tsbb_vswitch', [null, {payload: switchState}]);
    drain();
}
function inject(id) { send(id, {payload: byId[id].payload === '1' ? 1 : 0}); drain(); }
function result() {
    return {setting: setting, switchState: switchState, commands: commands,
            pending: jobs.length, statuses: statuses, warnings: warnings};
}
init();
NOW += 10000;
__SCENARIO__
print(JSON.stringify(result()));
"""


def run_js(flow, scenario, setting=0, switch=0):
    src = (SIMULATOR.replace("__FLOW__", json.dumps(flow))
           .replace("__SETTING__", str(setting)).replace("__SWITCH__", str(switch))
           .replace("__SCENARIO__", scenario))
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(src)
        path = f.name
    try:
        r = subprocess.run([JSC, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=30)
    finally:
        os.remove(path)
    if r.returncode != 0 or not r.stdout.strip():
        raise AssertionError("jsc failed: %s %s" % (r.stdout, r.stderr))
    return json.loads(r.stdout.strip().splitlines()[-1])


def load_flow():
    with open(FLOW) as f:
        return json.load(f)


class FlowFile(unittest.TestCase):
    def setUp(self):
        self.flow = load_flow()
        self.by_id = dict((n["id"], n) for n in self.flow)

    def test_every_wire_ends_at_a_node(self):
        for n in self.flow:
            for out in n.get("wires", []):
                for target in out:
                    self.assertIn(target, self.by_id, "%s -> %s" % (n["id"], target))

    def test_inputs_use_the_service_format_with_a_slash(self):
        # the dotted form goes through a legacy path that never delivers the
        # cached value; the nodes then show "disconnected" for minutes
        inputs = [n for n in self.flow if n["type"] == "victron-input-custom"]
        self.assertEqual(len(inputs), 4)
        for n in inputs:
            self.assertRegex(n["service"], r"^com\.victronenergy\.alternator/\d+$")

    def test_the_temperature_debug_node_is_off(self):
        self.assertFalse(self.by_id["tsbb_temp_debug"]["active"])


@unittest.skipIf(JSC is None, "no JavaScript engine (jsc) - flow logic not tested")
class FlowLogic(unittest.TestCase):
    def setUp(self):
        self.flow = load_flow()

    def test_two_quick_opposite_taps_do_not_loop(self):
        r = run_js(self.flow, """
            report(); completeAll(5);
            tap(1); tap(0);
            completeAll(50);
        """)
        self.assertEqual(r["pending"], 0, "still running after 50 commands")
        self.assertLessEqual(len(r["commands"]), 4)
        self.assertEqual(r["setting"], 0)          # the last wish wins
        self.assertEqual(r["switchState"], 0)

    def test_the_stored_switch_state_does_not_overwrite_the_setting(self):
        # switched on from the console; the switch still has 0 stored and
        # reports it after the deploy
        r = run_js(self.flow, "report(); completeAll(10);", setting=1, switch=0)
        self.assertEqual(r["setting"], 1)
        self.assertEqual(r["switchState"], 1)
        self.assertEqual(len(r["commands"]), 1)    # one read, no write

    def test_a_second_command_waits_for_the_first(self):
        r = run_js(self.flow, """
            report(); completeAll(5);
            tap(1); tap(0);
            var running = jobs.length;
            completeAll(10);
            commands.push('running while tapped: ' + running);
        """)
        self.assertIn("running while tapped: 1", r["commands"])
        self.assertEqual(r["setting"], 0)

    def test_a_tap_switches_and_the_switch_follows_the_setting(self):
        r = run_js(self.flow, "report(); completeAll(5); tap(1); completeAll(10);")
        self.assertEqual(r["setting"], 1)
        self.assertEqual(r["switchState"], 1)
        self.assertEqual(r["pending"], 0)

    def test_manual_injects_work_and_nothing_writes_mode(self):
        r = run_js(self.flow, "inject('tsbb_on'); completeAll(10);")
        self.assertEqual(r["setting"], 1)
        self.assertTrue(r["commands"])
        for cmd in r["commands"]:
            self.assertNotIn("/Mode", cmd)

    def test_a_failure_shows_the_real_setting_on_the_switch(self):
        r = run_js(self.flow, """
            report(); completeAll(5);
            tap(1);
            var job = jobs.shift();
            job[1].payload = 'failed: setting not written: access denied\\nRESULT=0';
            send(job[0], [job[1], null, null]); drain();
        """)
        self.assertEqual(r["switchState"], 0)
        texts = [s[1].get("text", "") for s in r["statuses"] if s[0] == "tsbb_status"]
        self.assertTrue(any(t.startswith("failed") for t in texts), texts)


class Stubs(object):
    """Stand-ins for dbus, svc and sleep on the GX."""

    def __init__(self, setting=0, svc_error="", services=("start-gui",), setvalue_ok=True):
        self.dir = tempfile.mkdtemp(prefix="tsbb-flow-")
        self.bin = os.path.join(self.dir, "bin")
        self.service = os.path.join(self.dir, "service")
        os.makedirs(self.bin)
        for s in services:
            os.makedirs(os.path.join(self.service, s))
        self.state = os.path.join(self.dir, "setting")
        self.svc_log = os.path.join(self.dir, "svc.log")
        with open(self.state, "w") as f:
            f.write("%d\n" % setting)
        self.script("dbus", """#!/bin/sh
case "$4" in
    GetValue) cat "%s" ;;
    SetValue) %s ;;
esac
""" % (self.state, 'echo "$5" > "%s"' % self.state if setvalue_ok
       else 'echo "Error: access denied" >&2; exit 1'))
        # daemontools svc: warns on stderr and exits 0 even when it failed
        self.script("svc", """#!/bin/sh
echo "$2" >> "%s"
%s
exit 0
""" % (self.svc_log, 'echo "%s" >&2' % svc_error if svc_error else ""))
        self.script("sleep", "#!/bin/sh\nexit 0\n")

    def script(self, name, text):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def run(self, command):
        command = command.replace("/service/", self.service + "/")
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))
        r = subprocess.run(["/bin/sh", "-c", command], env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=30)
        return r.stdout

    def svc_calls(self):
        if not os.path.exists(self.svc_log):
            return []
        with open(self.svc_log) as f:
            return [os.path.basename(line.strip()) for line in f]

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


@unittest.skipIf(JSC is None, "no JavaScript engine (jsc) - flow commands not tested")
class FlowCommands(unittest.TestCase):
    """The shell text the flow hands to its exec node, run for real."""

    def command(self, value):
        r = run_js(load_flow(), "deliver('tsbb_cmd', {payload: %d}); drain();" % value)
        return r["commands"][-1]

    def run_case(self, value=1, **stubs):
        s = Stubs(**stubs)
        try:
            return s.run(self.command(value)), s.svc_calls()
        finally:
            s.close()

    def test_switching_restarts_the_gui(self):
        out, calls = self.run_case()
        self.assertIn("switched", out)
        self.assertIn("RESULT=1", out)
        self.assertEqual(calls, ["start-gui"])

    def test_a_refused_svc_is_a_failure(self):
        # svc exits 0 and only complains on stderr
        out, _calls = self.run_case(
            svc_error="svc: warning: unable to control /service/start-gui: access denied")
        self.assertNotIn("switched", out)
        self.assertIn("failed", out)
        self.assertIn("access denied", out)

    def test_older_venus_restarts_gui(self):
        out, calls = self.run_case(services=("gui",))
        self.assertIn("switched", out)
        self.assertEqual(calls, ["gui"])

    def test_the_same_value_does_nothing(self):
        out, calls = self.run_case(setting=1)
        self.assertIn("unchanged", out)
        self.assertEqual(calls, [])

    def test_a_refused_write_is_reported_with_the_real_value(self):
        out, calls = self.run_case(setvalue_ok=False)
        self.assertIn("failed", out)
        self.assertIn("RESULT=0", out)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
