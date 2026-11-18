"""Tests for rot-radar-report.sh, run under /bin/bash."""
import os
import re
import shutil
import time
import unittest

import _common as c

GOOD_RULE = c.rule_text(desc="first rule", severity="high")
OTHER_RULE = c.rule_text(desc="second rule", severity="low", pattern="haystack")


class ReportTest(c.Scratch):
    def setUp(self):
        super().setUp()
        self.root = self.path("root")
        c.make_repo(os.path.join(self.root, "a"), {"f.txt": "needle\nneedle\nhaystack\n"})
        c.make_repo(os.path.join(self.root, "b"), {"f.txt": "nothing\n"})
        self.rules = c.make_rules(self.path("rules"), {"needle": GOOD_RULE, "straw": OTHER_RULE})
        self.out = self.path("reports")

    def report(self, *args, rules=None, extra=None, cwd=None):
        env = {"ROT_RADAR_RULES": rules or self.rules}
        if extra:
            env.update(extra)
        return c.run([c.BASH, c.REPORT] + list(args), cwd=cwd, home=self.home, extra=env)

    def days(self):
        # The report uses the local date; accept either side of a midnight change.
        return {time.strftime("%Y-%m-%d"), time.strftime("%Y-%m-%d", time.localtime(time.time() - 5))}

    def run_ok(self, *args, **kw):
        before = self.days()
        r = self.report("--root", self.root, "--out", self.out, *args, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        path = r.stdout.strip()
        self.assertEqual(r.stdout, path + "\n")
        return r, path, before | self.days()

    # ---- file, heading, summary, blocks ------------------------------------------
    def test_file_name_printed_path_and_heading(self):
        r, path, days = self.run_ok()
        m = re.match(r"^(.*)/rot-radar-(\d{4}-\d{2}-\d{2})\.md$", path)
        self.assertIsNotNone(m, path)
        self.assertEqual(m.group(1), self.out)
        self.assertIn(m.group(2), days)
        with open(path) as fh:
            text = fh.read()
        self.assertTrue(text.startswith("# Rot radar report %s\n\n" % m.group(2)), text[:60])
        self.assertEqual(os.listdir(self.out), ["rot-radar-%s.md" % m.group(2)])

    def test_summary_has_one_line_per_rule_in_name_order(self):
        r, path, _ = self.run_ok()
        with open(path) as fh:
            text = fh.read()
        summary = [ln for ln in text.splitlines() if ln.startswith("- ")]
        self.assertEqual(summary, [
            "- needle [high]: TOTAL: 2 hits in 1 of 2 repositories scanned",
            "- straw [low]: TOTAL: 1 hits in 1 of 2 repositories scanned",
        ])

    def test_each_rule_has_a_heading_and_a_fenced_block_with_the_engine_output(self):
        r, path, _ = self.run_ok()
        with open(path) as fh:
            text = fh.read()
        engine_out = c.engine(["needle", "--root", self.root], home=self.home,
                              extra={"ROT_RADAR_RULES": self.rules}).stdout
        self.assertIn("## needle\n\n```\n" + engine_out + "```\n\n", text)
        engine_out = c.engine(["straw", "--root", self.root], home=self.home,
                              extra={"ROT_RADAR_RULES": self.rules}).stdout
        self.assertIn("## straw\n\n```\n" + engine_out + "```\n\n", text)
        self.assertEqual(text.count("```"), 4)
        self.assertLess(text.index("## needle"), text.index("## straw"))
        self.assertLess(text.index("- straw"), text.index("## needle"))

    def test_the_body_holds_no_time_of_day(self):
        r, path, _ = self.run_ok()
        with open(path) as fh:
            text = fh.read()
        self.assertIsNone(re.search(r"\d{1,2}:\d{2}", text), text)

    def test_same_bytes_on_a_second_run(self):
        r, path, _ = self.run_ok()
        with open(path, "rb") as fh:
            first = fh.read()
        r2, path2, _ = self.run_ok()
        self.assertEqual(path, path2)
        with open(path2, "rb") as fh:
            self.assertEqual(fh.read(), first)
        self.assertEqual(len(os.listdir(self.out)), 1)

    def test_a_second_run_replaces_the_days_file(self):
        r, path, _ = self.run_ok()
        with open(path, "w") as fh:
            fh.write("old junk that must not survive\n" * 50)
        self.run_ok()
        with open(path) as fh:
            text = fh.read()
        self.assertNotIn("old junk", text)
        self.assertTrue(text.startswith("# Rot radar report"))

    def test_the_report_follows_the_repositories(self):
        r, path, _ = self.run_ok()
        c.write(os.path.join(self.root, "a", "g.txt"), "needle\n")
        c.git(os.path.join(self.root, "a"), "add", "-A")
        r2, path2, _ = self.run_ok()
        with open(path2) as fh:
            self.assertIn("- needle [high]: TOTAL: 3 hits in 1 of 2 repositories scanned", fh.read())

    # ---- --out and --root -----------------------------------------------------------
    def test_out_is_created_when_missing_even_several_levels_deep(self):
        self.out = self.path("x", "y", "z")
        r, path, _ = self.run_ok()
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(path.startswith(self.out + "/"))

    def test_out_with_a_trailing_slash_prints_a_clean_path(self):
        self.out = self.path("slash") + "/"
        r, path, _ = self.run_ok()
        self.assertNotIn("//", path)
        self.assertTrue(os.path.isfile(path))

    def test_out_may_be_relative(self):
        before = self.days()
        os.makedirs(self.path("cwd"))
        r = self.report("--root", self.root, "--out", "rel-out", cwd=self.path("cwd"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"^rel-out/rot-radar-\d{4}-\d{2}-\d{2}\.md\n$")
        self.assertTrue(os.path.isfile(os.path.join(self.path("cwd"), r.stdout.strip())))
        self.assertEqual(os.listdir(self.path("cwd")), ["rel-out"])
        self.assertTrue(before)

    def test_the_root_can_come_from_the_environment(self):
        r = self.report("--out", self.out, extra={"ROT_RADAR_ROOT": self.root})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(r.stdout.strip()) as fh:
            self.assertIn("- needle [high]: TOTAL: 2 hits", fh.read())

    def test_the_default_rules_folder_is_beside_the_script(self):
        r = c.run([c.BASH, c.REPORT, "--root", self.root, "--out", self.out], home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(r.stdout.strip()) as fh:
            text = fh.read()
        names = [ln.split(" ")[1] for ln in text.splitlines() if ln.startswith("- ")]
        self.assertEqual(names, ["bare-except", "console-log", "dynamic-code", "home-path-leak",
                                 "silent-catch-js", "silent-stderr", "ts-any"])
        for name in names:
            self.assertIn("## %s\n" % name, text)

    # ---- exit codes ---------------------------------------------------------------------
    def test_no_out_is_exit_2_and_writes_nothing(self):
        r = self.report("--root", self.root)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertTrue(r.stderr.startswith("rot-radar-report:"), r.stderr)

    def test_no_root_is_exit_2_and_writes_nothing(self):
        r = self.report("--out", self.out)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertFalse(os.path.exists(self.out))

    def test_unknown_argument_and_missing_value_are_exit_2(self):
        for args in (["--bogus"], ["--out"], ["--out", "--root", self.root], ["stray"]):
            with self.subTest(args=args):
                r = self.report("--root", self.root, *args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(r.stdout, "")
        self.assertFalse(os.path.exists(self.out))

    def test_a_missing_root_is_exit_3_and_nothing_is_written(self):
        r = self.report("--root", self.path("nowhere"), "--out", self.out)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout, "")
        self.assertIn("nowhere", r.stderr)
        self.assertFalse(os.path.exists(self.out))

    def test_a_root_that_is_a_file_is_exit_3(self):
        c.write(self.path("plain"), "x")
        r = self.report("--root", self.path("plain"), "--out", self.out)
        self.assertEqual(r.returncode, 3)
        self.assertFalse(os.path.exists(self.out))

    def test_no_rules_is_exit_2_and_writes_nothing(self):
        empty = self.path("no-rules")
        os.makedirs(empty)
        r = self.report("--root", self.root, "--out", self.out, rules=empty)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertFalse(os.path.exists(self.out))

    def test_a_broken_rule_file_is_listed_as_could_not_run_and_sets_exit_2(self):
        rules = self.path("rules-broken")
        shutil.copytree(self.rules, rules)
        c.write(os.path.join(rules, "needle.rule"), "RULE_DESC=\"d\"\nbogus line\n")
        r = self.report("--root", self.root, "--out", self.out, rules=rules)
        self.assertEqual(r.returncode, 2)
        path = r.stdout.strip()
        with open(path) as fh:
            text = fh.read()
        lines = [ln for ln in text.splitlines() if ln.startswith("- ")]
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r"^- needle \[\?\]: could not run \(exit 2\): rot-radar: .*needle\.rule")
        self.assertEqual(lines[1], "- straw [low]: TOTAL: 1 hits in 1 of 2 repositories scanned")
        self.assertIn("## needle\n\n```\nrot-radar: ", text)
        self.assertIn("needle.rule", r.stderr)

    @unittest.skipIf(c.is_root(), "root can read a mode 000 file")
    def test_an_unreadable_rule_file_is_listed_and_sets_exit_2(self):
        rules = self.path("rules-locked")
        shutil.copytree(self.rules, rules)
        os.chmod(os.path.join(rules, "straw.rule"), 0)
        r = self.report("--root", self.root, "--out", self.out, rules=rules)
        self.assertEqual(r.returncode, 2, r.stderr)
        with open(r.stdout.strip()) as fh:
            text = fh.read()
        self.assertRegex(text, r"- straw \[\?\]: could not run \(exit 2\): ")
        self.assertIn("- needle [high]: TOTAL: 2 hits", text)
        os.chmod(os.path.join(rules, "straw.rule"), 0o644)

    def test_the_highest_exit_code_wins(self):
        rules = self.path("rules-mixed")
        shutil.copytree(self.rules, rules)
        c.write(os.path.join(rules, "aaa.rule"), "oops\n")
        os.makedirs(os.path.join(self.root, "bad", ".git"))
        r = self.report("--root", self.root, "--out", self.out, rules=rules)
        self.assertEqual(r.returncode, 3, r.stderr)
        with open(r.stdout.strip()) as fh:
            text = fh.read()
        self.assertIn("- aaa [?]: could not run (exit 2): ", text)
        self.assertIn("- needle [high]: TOTAL: 2 hits in 1 of 2 repositories scanned, 1 could not be scanned", text)

    def test_a_root_with_no_repository_is_exit_3_and_every_rule_is_listed_as_not_run(self):
        empty = self.path("empty-root")
        os.makedirs(empty)
        r = self.report("--root", empty, "--out", self.out)
        self.assertEqual(r.returncode, 3)
        with open(r.stdout.strip()) as fh:
            text = fh.read()
        lines = [ln for ln in text.splitlines() if ln.startswith("- ")]
        self.assertEqual(len(lines), 2)
        for ln in lines:
            self.assertIn("could not run (exit 3): rot-radar: ", ln)

    def test_engine_messages_still_reach_stderr(self):
        empty = self.path("empty-root")
        os.makedirs(empty)
        r = self.report("--root", empty, "--out", self.out)
        self.assertEqual(r.stderr.count("rot-radar: no git repository"), 2, r.stderr)

    def test_an_unwritable_out_is_exit_3(self):
        c.write(self.path("a-file"), "x")
        r = self.report("--root", self.root, "--out", self.path("a-file", "sub"))
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout, "")

    def test_help(self):
        r = self.report("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage: bash rot-radar-report.sh", r.stdout)


if __name__ == "__main__":
    unittest.main()
