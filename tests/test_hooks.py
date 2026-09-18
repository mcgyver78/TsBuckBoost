"""Tests for tools/release-check, tools/pre-commit and tools/pre-push.

Every test builds a throwaway repository with a small changelog, stages or
commits a change and runs the hook script directly - nothing is installed
and nothing here touches the real clone.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")

HISTORY = ("v1.3 - third\n  driver: c\n\n"
           "v1.2 - second\n  driver: b\n\n"
           "v1.1 - first\n  driver: a\n")


class Repo(object):
    def __init__(self, package=True):
        self.dir = tempfile.mkdtemp(prefix="tsbb-hooktest-")
        # git hands GIT_INDEX_FILE (in a worktree GIT_DIR as well) to its hooks.
        # A test running inside the pre-commit hook must not point its own
        # repository at the index of the real commit.
        self.env = dict((k, v) for k, v in os.environ.items() if not k.startswith("GIT_"))
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                        TSBB_SKIP_TESTS="1")
        for k in ("TSBB_ALLOW_CHANGELOG_EDIT", "TSBB_ALLOW_CHANGELOG_SHRINK"):
            self.env.pop(k, None)
        self.git("init", "-q", "-b", "latest")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")
        os.makedirs(os.path.join(self.dir, "tools"))
        for name in ("release-check", "pre-commit", "pre-push"):
            shutil.copy(os.path.join(TOOLS, name), os.path.join(self.dir, "tools", name))
        if package:
            self.write("changes", HISTORY)
            self.write("version", "v1.3\n")
            self.write("dbus-tsbb.py", 'VERSION = "1.3"\n')
        else:
            self.write("README.md", "hardware\n")
        self.git("add", "-A")
        self.git("commit", "-q", "--no-verify", "-m", "start")

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(("git",) + args, cwd=self.dir, env=self.env, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True).stdout.strip()

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, name):
        with open(os.path.join(self.dir, name)) as f:
            return f.read()

    def stage(self, files):
        for name, text in files.items():
            self.write(name, text)
        self.git("add", "-A")

    def pre_commit(self, **env):
        e = dict(self.env, **env)
        return subprocess.run(("sh", "tools/pre-commit"), cwd=self.dir, env=e,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)

    def pre_push(self, old_sha, remote="origin", **env):
        new_sha = self.git("rev-parse", "HEAD")
        line = "refs/heads/latest %s refs/heads/latest %s\n" % (new_sha, old_sha)
        e = dict(self.env, **env)
        return subprocess.run(("sh", "tools/pre-push", remote, "url"), cwd=self.dir,
                              env=e, input=line, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True)


class PreCommitChangelog(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def assertRefused(self, result):
        self.assertEqual(result.returncode, 1, "hook let it through:\n" + result.stderr)

    def assertPassed(self, result):
        self.assertEqual(result.returncode, 0, "hook refused:\n" + result.stderr)

    def test_prepending_an_entry_passes(self):
        self.repo.stage({"changes": "v1.4 - fourth\n  driver: d\n\n" + HISTORY,
                         "version": "v1.4\n", "dbus-tsbb.py": 'VERSION = "1.4"\n'})
        self.assertPassed(self.repo.pre_commit())

    def test_truncation_is_refused(self):
        self.repo.stage({"changes": "v1.3 - third\n  driver: c\n"})
        self.assertRefused(self.repo.pre_commit())

    def test_deletion_is_refused(self):
        self.repo.git("rm", "-q", "changes")
        self.assertRefused(self.repo.pre_commit())

    def test_rename_is_refused(self):
        self.repo.git("mv", "changes", "changelog")
        self.assertRefused(self.repo.pre_commit())

    def test_rename_by_case_only_is_refused(self):
        self.repo.git("mv", "changes", "Changes")
        self.assertRefused(self.repo.pre_commit())

    def test_same_size_rewrite_is_refused(self):
        self.repo.stage({"changes": "X" * len(HISTORY)})
        self.assertRefused(self.repo.pre_commit())

    def test_history_replaced_by_longer_text_is_refused(self):
        self.repo.stage({"changes": "v1.3 - rewritten\n" + "  more words\n" * 40})
        self.assertRefused(self.repo.pre_commit())

    def test_editing_the_newest_entry_passes(self):
        self.repo.stage({"changes": HISTORY.replace("driver: c", "driver: c, reworded")})
        self.assertPassed(self.repo.pre_commit())

    def test_editing_older_history_is_refused(self):
        self.repo.stage({"changes": HISTORY.replace("driver: a", "driver: a, reworded")})
        self.assertRefused(self.repo.pre_commit())

    def test_override_lets_a_history_edit_through(self):
        self.repo.stage({"changes": HISTORY.replace("driver: a", "driver: a, reworded")})
        self.assertPassed(self.repo.pre_commit(TSBB_ALLOW_CHANGELOG_EDIT="1"))
        self.assertPassed(self.repo.pre_commit(TSBB_ALLOW_CHANGELOG_SHRINK="1"))


class PreCommitVersions(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_version_constant_left_behind_is_refused(self):
        # the state of 958dfd0: package v1.20, driver still says 1.19
        self.repo.stage({"changes": "v1.4 - fourth\n\n" + HISTORY, "version": "v1.4\n"})
        self.assertEqual(self.repo.pre_commit().returncode, 1)

    def test_changelog_left_behind_is_refused(self):
        self.repo.stage({"version": "v1.4\n", "dbus-tsbb.py": 'VERSION = "1.4"\n'})
        self.assertEqual(self.repo.pre_commit().returncode, 1)

    def test_branch_without_package_files_passes(self):
        hw = Repo(package=False)
        try:
            hw.stage({"README.md": "hardware, changed\n"})
            self.assertEqual(hw.pre_commit().returncode, 0)
        finally:
            hw.close()


class PreCommitTests(unittest.TestCase):
    """The hook runs tests/ when a covered path is staged, and a failing
    test stops the commit."""

    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def run_with_test(self, body):
        self.repo.write("tests/test_probe.py",
                        "import unittest\n\nclass T(unittest.TestCase):\n"
                        "    def test_it(self):\n        %s\n" % body)
        self.repo.stage({"dbus-tsbb.py": 'VERSION = "1.3"\n# changed\n'})
        return self.repo.pre_commit(TSBB_SKIP_TESTS="")

    def test_failing_test_blocks_the_commit(self):
        self.assertEqual(self.run_with_test("self.fail('red')").returncode, 1)

    def test_passing_test_lets_the_commit_through(self):
        self.assertEqual(self.run_with_test("pass").returncode, 0)

    def test_tests_run_without_the_variables_git_gives_its_hooks(self):
        self.repo.write("tests/test_probe.py",
                        "import os, unittest\n\nclass T(unittest.TestCase):\n"
                        "    def test_it(self):\n"
                        "        self.assertNotIn('GIT_INDEX_FILE', os.environ)\n")
        self.repo.stage({"dbus-tsbb.py": 'VERSION = "1.3"\n# changed\n'})
        index = os.path.join(self.repo.dir, ".git", "index")
        result = self.repo.pre_commit(TSBB_SKIP_TESTS="", GIT_INDEX_FILE=index)
        self.assertEqual(result.returncode, 0, result.stderr)


class Isolation(unittest.TestCase):
    def test_variables_of_a_surrounding_commit_do_not_leak_in(self):
        saved = dict((k, os.environ.get(k)) for k in ("GIT_INDEX_FILE", "GIT_DIR"))
        os.environ["GIT_INDEX_FILE"] = "/nonexistent/tsbb-test/index"
        os.environ["GIT_DIR"] = "/nonexistent/tsbb-test/.git"
        try:
            repo = Repo()
            try:
                repo.stage({"changes": "v1.3 - third\n"})
                self.assertEqual(repo.pre_commit().returncode, 1)
            finally:
                repo.close()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class PrePush(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.base = self.repo.git("rev-parse", "HEAD")

    def tearDown(self):
        self.repo.close()

    def commit(self, files):
        self.repo.stage(files)
        self.repo.git("commit", "-q", "--no-verify", "-m", "change")

    def test_truncation_committed_elsewhere_is_stopped(self):
        # the way f797818 and 958dfd0 arrived: committed without the hook
        self.commit({"changes": "v1.4 - fourth\n\n"})
        self.commit({"README": "unrelated\n"})
        result = self.repo.pre_push(self.base)
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_clean_commits_pass(self):
        self.commit({"changes": "v1.4 - fourth\n\n" + HISTORY, "version": "v1.4\n",
                     "dbus-tsbb.py": 'VERSION = "1.4"\n'})
        self.commit({"README": "unrelated\n"})
        self.assertEqual(self.repo.pre_push(self.base).returncode, 0)

    def test_new_remote_checks_the_whole_history(self):
        self.commit({"changes": "v1.3 - third\n"})
        self.assertEqual(self.repo.pre_push("0" * 40, remote="fresh").returncode, 1)


if __name__ == "__main__":
    unittest.main()
