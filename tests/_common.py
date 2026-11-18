"""Shared helpers for the test suite.

Everything here builds scratch folders and repositories under a temporary
folder. Every git call names its target with -C, runs with an empty global
config and HOME pointed at the scratch folder, so the tester's own git
settings and ignore list cannot change a result. No commit is ever made, so
no identity is needed.
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HUNT = os.path.join(REPO, "hunt.sh")
ENGINE = os.path.join(REPO, "rot-radar.sh")
REPORT = os.path.join(REPO, "rot-radar-report.sh")
DEMO = os.path.join(REPO, "examples", "demo.sh")
RULES = os.path.join(REPO, "rules")

BASH = "/bin/bash"
SH = "/bin/sh"
DASH = shutil.which("dash")

# Tools the scripts call, linked into a PATH folder by tests that remove git.
TOOLS = ["sh", "bash", "grep", "find", "sort", "sed", "tr", "wc", "cut",
         "mktemp", "date", "mkdir", "cat", "rm", "dirname", "printf"]


def shells():
    """The shells hunt.sh is tested under."""
    out = [SH, BASH]
    if DASH:
        out.append(DASH)
    return out


def base_env(home):
    """A small, fixed environment for every child process."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": home,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    return env


def run(argv, cwd=None, env=None, home=None, extra=None):
    """Run a command and return the CompletedProcess with text output."""
    if env is None:
        env = base_env(home or tempfile.gettempdir())
    env = dict(env)
    if extra:
        env.update(extra)
    return subprocess.run(
        argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, errors="replace", timeout=120)


def write(path, content, binary=False):
    """Write a file, creating parent folders."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if binary else "w"
    with open(path, mode) as fh:
        fh.write(content)


def git(repo, *args, home=None):
    """Run git against a scratch repository, returning the CompletedProcess."""
    env = base_env(home or os.path.dirname(repo))
    return subprocess.run(
        ["git", "-C", repo] + list(args), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, errors="replace", timeout=60)


def make_repo(path, files=None):
    """Create a repository at path with the given tracked files.

    files maps a relative path to str or bytes content. The files are added
    with `git add -A` and nothing else; there is no commit.
    """
    os.makedirs(path, exist_ok=True)
    r = git(path, "init", "-q")
    assert r.returncode == 0, r.stderr
    for rel, content in (files or {}).items():
        write(os.path.join(path, rel), content, binary=isinstance(content, bytes))
    r = git(path, "add", "-A")
    assert r.returncode == 0, r.stderr
    return path


def make_rules(folder, rules):
    """Write rule files. rules maps NAME to the text of NAME.rule."""
    os.makedirs(folder, exist_ok=True)
    for name, text in rules.items():
        write(os.path.join(folder, name + ".rule"), text)
    return folder


def rule_text(desc="a test rule", severity="med", glob="*.txt",
              pattern="needle", extra=""):
    return (
        'RULE_DESC="%s"\nRULE_SEVERITY="%s"\nRULE_GLOB="%s"\n'
        "RULE_PATTERN='%s'\n%s" % (desc, severity, glob, pattern, extra))


def engine(args, cwd=None, home=None, extra=None, shell=BASH):
    return run([shell, ENGINE] + list(args), cwd=cwd, home=home, extra=extra)


def make_unreadable(path):
    os.chmod(path, 0)


def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def bash_is_old():
    """True when /bin/bash is older than 4.4 (an empty array under set -u fails)."""
    r = subprocess.run(
        [BASH, "-c", 'echo "${BASH_VERSINFO[0]} ${BASH_VERSINFO[1]}"'],
        stdout=subprocess.PIPE, universal_newlines=True)
    major, minor = [int(x) for x in r.stdout.split()]
    return (major, minor) < (4, 4)


class Scratch(unittest.TestCase):
    """A test case with a temporary folder in self.tmp (and self.home)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="rr-test-")
        self.tmp = os.path.realpath(self._td.name)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        # Restore permissions so the folder can be removed.
        for dirpath, dirnames, filenames in os.walk(self.tmp):
            for name in dirnames + filenames:
                p = os.path.join(dirpath, name)
                try:
                    if not os.path.islink(p):
                        os.chmod(p, os.stat(p).st_mode | stat.S_IRWXU)
                except OSError:
                    pass
        self._td.cleanup()

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)
