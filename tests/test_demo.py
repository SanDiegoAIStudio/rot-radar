"""Tests for examples/demo.sh, run under /bin/bash."""
import os
import unittest

import _common as c


def snapshot(folder):
    seen = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            st = os.stat(p)
            seen[os.path.relpath(p, folder)] = (st.st_size, st.st_mtime_ns)
    return seen


class DemoTest(c.Scratch):
    def demo(self, cwd=None):
        tmpdir = self.path("demo-tmp")
        os.makedirs(tmpdir, exist_ok=True)
        r = c.run([c.BASH, c.DEMO], cwd=cwd or self.tmp, home=self.home, extra={"TMPDIR": tmpdir})
        return r, tmpdir

    def test_exit_0_and_the_count_lines_before_and_after_the_comment(self):
        r, _ = self.demo()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        out = r.stdout
        self.assertIn("$ sh hunt.sh scripts\n"
                      "scripts/backup.sh\nscripts/cleanup.sh\nscripts/sync.sh\n"
                      "3 lines in 3 files throw stderr away\nexit code: 1\n", out)
        self.assertEqual(out.count("\nTOTAL: 3 hits in 2 of 2 repositories scanned\n"), 1)
        self.assertEqual(out.count("\nTOTAL: 2 hits in 1 of 2 repositories scanned\n"), 1)
        self.assertLess(out.index("TOTAL: 3 hits"), out.index("TOTAL: 2 hits"))
        self.assertIn("- silent-stderr [high]: TOTAL: 2 hits in 1 of 2 repositories scanned\n", out)
        self.assertTrue(out.endswith("demo finished: every step behaved as expected\n"))

    def test_the_untracked_file_and_the_exempt_scripts_do_not_count(self):
        r, _ = self.demo()
        self.assertNotIn("draft.sh", r.stdout)
        self.assertNotIn("scripts/rotate.sh", r.stdout)
        self.assertNotIn("scripts/report.sh", r.stdout)

    def test_the_output_is_the_same_on_every_run_and_holds_no_absolute_path(self):
        first, tmpdir = self.demo()
        second, _ = self.demo(cwd=self.path("home"))
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn("reports/rot-radar-YYYY-MM-DD.md\n", first.stdout)
        for token in first.stdout.split():
            self.assertFalse(token.startswith("/") and len(token) > 1 and token not in ("/dev/null",),
                             token)
        self.assertNotIn(self.tmp, first.stdout)

    def test_nothing_is_written_inside_the_repository_and_the_temp_folder_is_removed(self):
        before = snapshot(c.REPO)
        r, tmpdir = self.demo()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(snapshot(c.REPO), before)
        self.assertEqual(os.listdir(tmpdir), [])

    def test_the_demo_runs_from_any_folder_and_does_not_need_the_executable_bit(self):
        r, _ = self.demo(cwd="/")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.access(c.DEMO, os.X_OK))

    def test_the_demo_ignores_a_root_or_rules_folder_set_in_the_environment(self):
        r = c.run([c.BASH, c.DEMO], cwd=self.tmp, home=self.home,
                  extra={"ROT_RADAR_ROOT": self.path("nowhere"), "ROT_RADAR_RULES": self.path("nowhere"),
                         "TMPDIR": self.tmp})
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
