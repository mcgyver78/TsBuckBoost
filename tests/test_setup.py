"""Tests for setup without SetupHelper and without a GX device.

A stand-in for SetupHelper's IncludeHelpers records what setup asks for
(installService, removeService, log messages), and udevadm is a stub. The
udev rule and its copy under /data/conf live in a temporary directory.
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(ROOT, "setup")

HELPERS = r"""# stand-in for /data/SetupHelper/HelperResources/IncludeHelpers
packageName=TsBuckBoost
case "$1" in
    install) scriptAction=INSTALL ;;
    uninstall) scriptAction=UNINSTALL ;;
    *) scriptAction=NONE ;;
esac
record() { echo "$*" >> "$TSBB_TEST_LOG"; }
installService() { record "installService $1"; }
removeService() { record "removeService $1"; }
logMessage() { record "log $*"; }
standardActionPrompt() { record "prompt"; }
endScript() { record "endScript"; exit 0; }
"""

RULE = ('ACTION=="add", SUBSYSTEM=="tty", '
        'ENV{ID_SERIAL_SHORT}=="d437624d05c4ec11a9c6a4f2d297222e", '
        'ENV{VE_SERVICE}="ignore"\n')


class Setup(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tsbb-setup-")
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        os.makedirs(os.path.join(self.dir, "rules.d"))
        os.makedirs(os.path.join(self.dir, "conf"))
        self.helpers = os.path.join(self.dir, "IncludeHelpers")
        with open(self.helpers, "w") as f:
            f.write(HELPERS)
        udevadm = os.path.join(self.bin, "udevadm")
        with open(udevadm, "w") as f:
            f.write('#!/bin/sh\necho "udevadm $*" >> "$TSBB_TEST_LOG"\n')
        os.chmod(udevadm, os.stat(udevadm).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.dir, "log")
        self.store = os.path.join(self.dir, "conf", "tsbuckboost-udev.rules")
        self.rule = os.path.join(self.dir, "rules.d", "99-tsbuckboost.rules")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_setup(self, action):
        env = dict(os.environ, TSBB_SETUP_HELPERS=self.helpers, TSBB_TEST_LOG=self.log,
                   TSBB_UDEV_STORE=self.store, TSBB_UDEV_RULE=self.rule,
                   PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))
        r = subprocess.run(["bash", SETUP, action], env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().splitlines()

    def write(self, path, text=RULE):
        with open(path, "w") as f:
            f.write(text)

    def test_install_brings_the_rule_back_after_a_firmware_update(self):
        self.write(self.store)
        calls = self.run_setup("install")
        with open(self.rule) as f:
            self.assertEqual(f.read(), RULE)
        self.assertIn("udevadm control --reload", calls)
        self.assertIn("installService TsBuckBoost", calls)

    def test_install_without_a_rule_installs_the_service_only(self):
        calls = self.run_setup("install")
        self.assertFalse(os.path.exists(self.rule))
        self.assertIn("installService TsBuckBoost", calls)
        self.assertNotIn("udevadm control --reload", calls)

    def test_uninstall_takes_the_rule_away(self):
        self.write(self.store)
        self.write(self.rule)
        calls = self.run_setup("uninstall")
        self.assertFalse(os.path.exists(self.rule))
        self.assertFalse(os.path.exists(self.store))
        self.assertIn("udevadm control --reload", calls)
        self.assertIn("removeService TsBuckBoost", calls)


if __name__ == "__main__":
    unittest.main()
