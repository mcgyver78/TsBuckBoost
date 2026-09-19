#!/usr/bin/env python3
"""Builds extras/nodered-separate-temp-sensors.json from readable JavaScript.

    python3 tools/build-flow.py [output file]

The JavaScript and shell texts live here as raw strings; json.dump does the
escaping. The node ids stay those of the first flow, so that an import into
Node-RED replaces the old nodes instead of adding a second set. Do not edit
the JSON by hand: change this file, run it, and test with tests/test_flow.py,
which also checks that the JSON is exactly what this file builds.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "extras", "nodered-separate-temp-sensors.json")

TAB_INFO = """A switch that shows the individual Buck-Boost temperatures as separate
Venus devices or hides them again, and four inputs that read those
temperatures straight from the converter's own service - these work
whether the switch is on or off.

The switch writes the settings value
/Settings/Devices/tsbuckboost/SeparateTempSensors on
com.victronenergy.settings - never the converter's /Mode path, which is
the pin 1 mirror. The driver (v1.21 or later) restarts itself when that
value changes, and the device list on the GX follows by itself. Nothing
else is restarted."""

NOTE_INFO = """Setting: /Settings/Devices/tsbuckboost/SeparateTempSensors
1 = on, 0 = off. The value survives reboots and package updates.

One command runs at a time. A tap while one is running only replaces the
pending wish, which runs afterwards - so quick taps end in the last one,
with at most one extra restart.

The switch always shows the setting as read back from the GX: after every
command, on every start of the flow and every ten minutes. A change made
from the console therefore shows up on the switch as well. The first report
of the switch after a deploy is its stored state, not a tap; it is answered
by reading the setting, never by writing it.

Needs the TsBuckBoost driver v1.21 or later, which restarts itself when the
setting changes. Up to v1.21 the flow restarted the GX user interface as
well; Node-RED runs without root rights, svc answered "access denied", and
every switch was reported as failed. The device list does not need it."""

TEMP_NOTE_INFO = """These read the paths the driver always publishes on its own service,
whether the separate temperature devices are switched on or not.

"Only changes" is deliberately off: a temperature can sit on the same
value for minutes, and with it on the nodes stay silent - and show
disconnected - until the reading finally moves. Off, the Victron nodes
re-send the last value every five seconds and immediately on a change.
The debug node below is off, too; switch it on while you look.

The service is stored as com.victronenergy.alternator/<device instance>;
40 is the driver's default, yours may differ - check with:
  dbus -y com.victronenergy.settings \\
       /Settings/Devices/tsbuckboost/ClassAndVrmInstance GetValue
If a node shows disconnected, open it, pick the Buck-Boost from the list
and deploy. The CAN sensor node delivers an empty value while no TS Temp
sensor is connected to the converter."""

FROM_SWITCH = r"""// Marks what comes from the virtual switch, so that "build settings command"
// can tell its reports from the commands of the inject nodes.
msg.tsbbSource = 'switch';
return msg;"""

CMD_INIT = r"""// A deploy or a restart: the next report of the switch is its stored state,
// not a tap, and no command is running any more.
flow.set('tsbbSwitchSeen', false);
flow.set('tsbbBusy', 0);
flow.set('tsbbPending', undefined);"""

CMD = r"""// One command at a time. While one runs, a newer wish replaces the pending
// one, and "result" starts it when the current command is done. Two quick
// taps used to run in parallel, and each result fed back into the switch
// started yet another run: driver and GX display restarted every few seconds.
//
// The virtual switch reports its state after every deploy and whenever
// "sync switch" sets it. Its first report after a (re)start is not a tap:
// it only starts a read of the setting, which then sets the switch. After
// that, only a change against the state last seen is a command.
var P = '/Settings/Devices/tsbuckboost/SeparateTempSensors';
var GET = 'dbus -y com.victronenergy.settings ' + P + " GetValue 2>/dev/null | tr -d ' \\n'";
var value = null;
if (msg.tsbbSync !== true) {
    // Accepts 1/0, true/false, "on"/"off", "true"/"false" (any case) or an
    // object with .state - depending on what the sender delivers. Anything
    // else is refused: a guess could restart the driver for nothing.
    var p = msg.payload;
    if (p !== null && typeof p === 'object') {
        p = (p.state !== undefined) ? p.state : p.value;
    }
    if (typeof p === 'string') { p = p.trim().toLowerCase(); }
    if (p === 1 || p === true || p === '1' || p === 'on' || p === 'true') {
        value = 1;
    } else if (p === 0 || p === false || p === '0' || p === 'off' || p === 'false') {
        value = 0;
    } else {
        node.warn('ignored payload: ' + JSON.stringify(msg.payload));
        node.status({fill: 'yellow', shape: 'ring', text: 'ignored payload'});
        return null;
    }
    if (msg.tsbbSource === 'switch') {
        var seen = flow.get('tsbbSwitchState');
        var first = !flow.get('tsbbSwitchSeen');
        flow.set('tsbbSwitchSeen', true);
        flow.set('tsbbSwitchState', value);
        if (first) {
            value = null;
        } else if (seen === value) {
            return null;
        }
    }
}
var busy = flow.get('tsbbBusy') || 0;
if (busy && Date.now() - busy < 60000) {
    flow.set('tsbbPending', value === null ? 'sync' : value);
    node.status({fill: 'blue', shape: 'ring',
                 text: 'queued: ' + (value === null ? 'read' : 'switch to ' + value)});
    return null;
}
flow.set('tsbbBusy', Date.now());
msg.tsbbValue = value;
if (value === null) {
    msg.payload = 'echo "RESULT=$(' + GET + ')"';
    node.status({fill: 'blue', shape: 'dot', text: 'reading the setting'});
    return msg;
}
// Only the setting is written, never the device path /Mode. The driver
// (v1.21 and later) restarts itself when the setting changes, and the device
// list on the GX follows by itself. Up to v1.21 the GX display was restarted
// here as well: Node-RED runs without root rights, svc answered "access
// denied", and every switch that had worked was reported as failed.
msg.payload = [
    'get() { ' + GET + '; }',
    'if [ "$(get)" = "' + value + '" ]; then',
    '    echo unchanged',
    'else',
    '    OUT=$(dbus -y com.victronenergy.settings ' + P + ' SetValue ' + value + ' 2>&1)',
    '    if [ "$(get)" = "' + value + '" ]; then',
    '        echo switched',
    '    else',
    '        echo "failed: setting not written: $OUT"',
    '    fi',
    'fi',
    'echo "RESULT=$(get)"'
].join('\n');
node.status({fill: 'blue', shape: 'dot', text: 'switching to ' + value});
return msg;"""

RESULT = r"""// The command prints its keyword line(s) and, last, RESULT=<the setting as
// read back>. The switch is set from that value - after a failure as well -
// and never from what was asked for.
var out = String(msg.payload || '').trim();
var m = out.match(/RESULT=([01])/);
var actual = m ? parseInt(m[1], 10) : null;
var text = out.replace(/^RESULT=.*$/m, '').trim();
var reading = msg.tsbbValue === null || msg.tsbbValue === undefined;
var state = actual === 1 ? 'on' : (actual === 0 ? 'off' : 'unknown');
var ok = true;
var report;
if (reading) {
    ok = actual !== null;
    report = ok ? 'setting is ' + state : 'setting not readable: ' + (text || 'no output');
} else if (/\bunchanged\b/.test(text) && actual === msg.tsbbValue) {
    report = 'already ' + state + ', nothing to do';
} else if (/\bswitched\b/.test(text) && actual === msg.tsbbValue) {
    report = 'separate temperature devices ' + state + ', driver restarts itself';
} else {
    ok = false;
    report = 'failed: ' + (text.replace(/failed: ?/g, '').replace(/\s*\n\s*/g, '; ') ||
        'no output - is the exec node allowed to run commands?') +
        ' (setting is ' + state + ')';
}
node.status({fill: ok ? 'green' : 'red', shape: 'dot', text: report});
flow.set('tsbbBusy', 0);
var pending = flow.get('tsbbPending');
flow.set('tsbbPending', undefined);
var next = null;
if (pending === 'sync') {
    next = {payload: 'read', tsbbSync: true};
} else if (pending === 0 || pending === 1) {
    next = {payload: pending};
}
return [reading ? null : {payload: report, tsbbOk: ok},
        actual === null ? null : {payload: actual},
        next];"""

SYNC = r"""// Sets the virtual switch to the setting as read back. The switch reports
// the change on its second output; "build settings command" finds it equal
// to the state recorded here and leaves it alone.
if (msg.payload !== 0 && msg.payload !== 1) { return null; }
flow.set('tsbbSwitchState', msg.payload);
return {payload: msg.payload};"""


def function(nid, name, func, x, y, wires, outputs=1, initialize=""):
    return {"id": nid, "type": "function", "z": "tsbb_tab", "name": name, "func": func,
            "outputs": outputs, "timeout": 0, "noerr": 0, "initialize": initialize,
            "finalize": "", "libs": [], "x": x, "y": y, "wires": wires}


def inject(nid, name, x, y, props, once=False, repeat="", once_delay=0.1):
    node = {"id": nid, "type": "inject", "z": "tsbb_tab", "name": name, "props": props,
            "repeat": repeat, "crontab": "", "once": once, "onceDelay": once_delay,
            "topic": "", "x": x, "y": y, "wires": [["tsbb_cmd"]]}
    for p in props:
        if p["p"] == "payload":
            node["payload"] = p["v"]
            node["payloadType"] = p["vt"]
            p.pop("v")
            p.pop("vt")
    return node


def temp_input(nid, path, name, y):
    service = "com.victronenergy.alternator/40"
    return {"id": nid, "type": "victron-input-custom", "z": "tsbb_tab",
            "service": service, "path": path,
            "serviceObj": {"service": service, "name": "Buck-Boost"},
            "pathObj": {"path": path, "type": "float", "name": name},
            "name": name, "onlyChanges": False, "x": 200, "y": y,
            "wires": [["tsbb_temp_debug"]]}


flow = [
    {"id": "tsbb_tab", "type": "tab", "label": "TsBuckBoost", "disabled": False,
     "info": TAB_INFO},
    {"id": "tsbb_note", "type": "comment", "z": "tsbb_tab",
     "name": "TsBuckBoost: show temperatures as separate devices",
     "info": NOTE_INFO, "x": 320, "y": 60, "wires": []},
    {"id": "tsbb_vswitch", "type": "victron-virtual-switch", "z": "tsbb_tab",
     "name": "Buck-Boost additional sensors", "outputs": 2,
     "switch_1_type": 1, "switch_1_initial": 0, "switch_1_label": "",
     "switch_1_customname": "Buck-Boost additional sensors",
     "switch_1_group": "TS_BuckBoost", "switch_1_include_measurement": False,
     "switch_1_rgb_color_wheel": False, "switch_1_cct_wheel": False,
     "switch_1_rgb_white_dimmer": False, "switch_1_show_ui_input": 1,
     "switch_1_passthrough_mode": "auto_only", "x": 200, "y": 160,
     "wires": [[], ["tsbb_from_switch"]]},
    function("tsbb_from_switch", "from the switch", FROM_SWITCH, 420, 160, [["tsbb_cmd"]]),
    inject("tsbb_on", "manual ON", 200, 220, [{"p": "payload", "v": "1", "vt": "num"}]),
    inject("tsbb_off", "manual OFF", 200, 260, [{"p": "payload", "v": "0", "vt": "num"}]),
    inject("tsbb_read", "read the setting", 210, 300,
           [{"p": "payload", "v": "read", "vt": "str"},
            {"p": "tsbbSync", "v": "true", "vt": "bool"}],
           once=True, repeat="600", once_delay=5),
    function("tsbb_cmd", "build settings command", CMD, 640, 220, [["tsbb_exec"]],
             initialize=CMD_INIT),
    {"id": "tsbb_exec", "type": "exec", "z": "tsbb_tab", "command": "",
     "addpay": "payload", "append": "", "useSpawn": "false", "timer": "30",
     "winHide": False, "oldrc": False, "name": "run on the GX device",
     "x": 860, "y": 220, "wires": [["tsbb_status"], [], []]},
    function("tsbb_status", "result", RESULT, 1060, 220,
             [["tsbb_debug"], ["tsbb_sync"], ["tsbb_cmd"]], outputs=3),
    {"id": "tsbb_debug", "type": "debug", "z": "tsbb_tab", "name": "status",
     "active": True, "tosidebar": True, "console": False, "tostatus": True,
     "complete": "payload", "targetType": "msg", "statusVal": "payload",
     "statusType": "auto", "x": 1250, "y": 180, "wires": []},
    function("tsbb_sync", "sync switch", SYNC, 1260, 260, [["tsbb_vswitch"]]),
    {"id": "tsbb_temp_note", "type": "comment", "z": "tsbb_tab",
     "name": "Temperatures straight from the converter - no extra devices needed",
     "info": TEMP_NOTE_INFO, "x": 380, "y": 380, "wires": []},
    temp_input("tsbb_in_board", "/Temperature/Board", "Board temperature", 420),
    temp_input("tsbb_in_mosfet1", "/Temperature/Mosfet1", "MOSFET 1 temperature", 480),
    temp_input("tsbb_in_mosfet2", "/Temperature/Mosfet2", "MOSFET 2 temperature", 540),
    temp_input("tsbb_in_can", "/Temperature/CanSensor", "CAN sensor temperature", 600),
    {"id": "tsbb_temp_debug", "type": "debug", "z": "tsbb_tab", "name": "temperatures",
     "active": False, "tosidebar": True, "console": False, "tostatus": False,
     "complete": "payload", "targetType": "msg", "statusVal": "", "statusType": "auto",
     "x": 520, "y": 510, "wires": []},
]

with open(OUT, "w") as f:
    json.dump(flow, f, indent=4, ensure_ascii=True)
    f.write("\n")
print("written: %s, %d nodes" % (OUT, len(flow)))
