"""Tests for rot-radar.sh, run under /bin/bash."""
import json
import os
import shutil
import unittest

import _common as c


def repo_line(path, count):
    return "  %-44s %5d\n" % (path, count)


class EngineTest(c.Scratch):
    def setUp(self):
        super().setUp()
        self.root = self.path("root")
        os.makedirs(self.root)
        self.rules = c.make_rules(self.path("rules"), {"needle": c.rule_text()})

    def eng(self, *args, rules=None, extra=None, cwd=None):
        env = {"ROT_RADAR_RULES": rules or self.rules}
        if extra:
            env.update(extra)
        return c.engine(list(args), cwd=cwd, home=self.home, extra=env)

    def scan(self, *args, **kw):
        return self.eng("needle", "--root", self.root, *args, **kw)

    def repo(self, rel, files):
        return c.make_repo(os.path.join(self.root, rel), files)

    # ---- counting -------------------------------------------------------
    def test_counts_per_repository_and_the_total(self):
        self.repo("a", {"a.txt": "needle\nneedle\nother\n"})
        self.repo("quiet", {"q.txt": "nothing here\n"})
        self.repo(os.path.join("grp", "c"), {"c.txt": "needle\n"})
        r = self.scan()
        expected = (
            "rot-radar: needle [med]\n"
            "  a test rule\n"
            "  searched: *.txt\n"
            "  excluded: (none)\n"
            "\n"
            + repo_line("a", 2)
            + repo_line("grp/c", 1)
            + "TOTAL: 3 hits in 2 of 3 repositories scanned\n")
        self.assertEqual(r.stdout, expected)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_repository_three_levels_down_is_not_found(self):
        self.repo("a", {"a.txt": "needle\n"})
        self.repo(os.path.join("x", "y", "z"), {"z.txt": "needle\n"})
        r = self.scan()
        self.assertTrue(r.stdout.endswith("TOTAL: 1 hits in 1 of 1 repositories scanned\n"), r.stdout)
        self.assertNotIn("x/y/z", r.stdout)

    def test_the_root_itself_is_named_dot(self):
        c.make_repo(self.root, {"t.txt": "needle\n"})
        r = self.scan()
        self.assertIn(repo_line(".", 1), r.stdout)
        self.assertEqual(r.returncode, 0)

    def test_untracked_and_binary_files_do_not_count(self):
        path = self.repo("a", {
            "tracked.txt": "needle\n",
            "blob.txt": b"\x00\x01 needle\n",
        })
        c.write(os.path.join(path, "later.txt"), "needle\nneedle\n")
        r = self.scan()
        self.assertIn(repo_line("a", 1), r.stdout)
        self.assertIn("TOTAL: 1 hits in 1 of 1 repositories scanned", r.stdout)

    def test_files_that_do_not_match_the_glob_do_not_count(self):
        self.repo("a", {"notes.md": "needle\n", "deep/dir/x.txt": "needle\n"})
        r = self.scan()
        self.assertIn(repo_line("a", 1), r.stdout)

    def test_order_is_count_high_to_low_then_path(self):
        self.repo("x", {"f.txt": "needle\n"})
        self.repo("z", {"f.txt": "needle\n" * 3})
        self.repo("y", {"f.txt": "needle\n" * 3})
        self.repo("w", {"f.txt": "needle\n" * 2})
        r = self.scan()
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith("  ") and ln[2:3] in "wxyz"]
        self.assertEqual([ln.split()[0] for ln in lines], ["y", "z", "w", "x"])

    # ---- --show and --limit -------------------------------------------------
    def test_show_prints_every_hit(self):
        self.repo("a", {"f.txt": "needle one\nskip\nneedle two\n"})
        r = self.scan("--show")
        self.assertIn(repo_line("a", 2) + "    f.txt:1:needle one\n    f.txt:3:needle two\n", r.stdout)
        self.assertNotIn("more not shown", r.stdout)

    def test_limit_cuts_the_hits_and_says_how_many_were_left_out(self):
        self.repo("a", {"f.txt": "needle\n" * 5})
        self.repo("b", {"f.txt": "needle\nneedle\n"})
        r = self.scan("--show", "--limit", "2")
        self.assertIn(repo_line("a", 5) + "    f.txt:1:needle\n    f.txt:2:needle\n    (3 more not shown)\n", r.stdout)
        self.assertIn(repo_line("b", 2) + "    f.txt:1:needle\n    f.txt:2:needle\n" + "TOTAL", r.stdout)
        r = self.scan("--show", "--limit", "1")
        self.assertIn("    (1 more not shown)\n", r.stdout)
        self.assertEqual(r.stdout.count("not shown"), 2)

    def test_limit_needs_show_and_a_positive_number(self):
        self.repo("a", {"f.txt": "needle\n"})
        for args in (["--limit", "2"], ["--show", "--limit", "0"], ["--show", "--limit", "x"],
                     ["--show", "--limit", "-1"], ["--show", "--limit", ""]):
            with self.subTest(args=args):
                r = self.scan(*args)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(r.stdout, "")
                self.assertTrue(r.stderr.startswith("rot-radar:"), r.stderr)

    # ---- --repos ------------------------------------------------------------
    def test_repos_keeps_only_the_named_repositories(self):
        self.repo("a", {"f.txt": "needle\n"})
        self.repo("b", {"f.txt": "needle\n"})
        self.repo(os.path.join("grp", "c"), {"f.txt": "needle\n"})
        r = self.scan("--repos", "b,grp/c")
        self.assertNotIn(repo_line("a", 1), r.stdout)
        self.assertIn(repo_line("b", 1), r.stdout)
        self.assertIn(repo_line("grp/c", 1), r.stdout)
        self.assertIn("TOTAL: 2 hits in 2 of 2 repositories scanned", r.stdout)

    def test_repos_with_an_unknown_name_is_exit_2_and_names_it(self):
        self.repo("a", {"f.txt": "needle\n"})
        r = self.scan("--repos", "a,nope")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertIn("nope", r.stderr)

    # ---- rule excludes ------------------------------------------------------
    def test_rule_excludes_take_effect_and_are_printed(self):
        rules = c.make_rules(self.path("rules2"), {
            "needle": c.rule_text(extra='RULE_EXCLUDE="vendor/** **/fixtures/**"\n')})
        self.repo("a", {"vendor/v.txt": "needle\n", "src/fixtures/f.txt": "needle\n",
                        "fixtures/top.txt": "needle\n", "src/real.txt": "needle\n"})
        r = self.scan(rules=rules)
        self.assertIn("  excluded: vendor/** **/fixtures/**\n", r.stdout)
        self.assertIn(repo_line("a", 1), r.stdout)
        self.assertIn("TOTAL: 1 hits in 1 of 1 repositories scanned", r.stdout)

    def test_a_rule_with_no_excludes_runs_under_the_stock_bash(self):
        # With set -u, an unguarded empty array is an error before bash 4.4.
        self.repo("a", {"f.txt": "needle\n"})
        r = c.engine(["needle", "--root", self.root], home=self.home,
                     extra={"ROT_RADAR_RULES": self.rules}, shell="/bin/bash")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("TOTAL: 1 hits in 1 of 1 repositories scanned", r.stdout)

    def test_rule_with_fix_hint_prints_it(self):
        rules = c.make_rules(self.path("rules3"), {
            "needle": c.rule_text(extra='RULE_FIX_HINT="do the better thing"\n')})
        self.repo("a", {"f.txt": "needle\n"})
        r = self.scan(rules=rules)
        self.assertIn("  a test rule\n  fix: do the better thing\n  searched: *.txt\n", r.stdout)

    # ---- JSON ---------------------------------------------------------------
    def test_json_is_one_line_and_reads_back_exactly(self):
        weird = 'we ird"na\\me'
        self.repo(weird, {"f.txt": "needle\nneedle\n"})
        self.repo("plain", {"f.txt": "nothing\n"})
        r = self.scan("--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("\n"), 1)
        data = json.loads(r.stdout)
        self.assertEqual(data, {
            "rule": "needle", "severity": "med", "scanned": 2, "total": 2,
            "repos": [{"repo": "plain", "hits": 0}, {"repo": weird, "hits": 2}],
            "could_not": []})
        self.assertEqual(list(data), ["rule", "severity", "scanned", "total", "repos", "could_not"])

    def test_json_escapes_tab_and_carriage_return_and_removes_other_control_characters(self):
        self.repo("tab\there", {"f.txt": "needle\n"})
        self.repo("cr\rhere", {"f.txt": "needle\n"})
        self.repo("ctl\x01x", {"f.txt": "needle\n"})
        r = self.scan("--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("\t", r.stdout)
        self.assertNotIn("\x01", r.stdout)
        self.assertEqual(r.stdout.count("\n"), 1)
        names = sorted(x["repo"] for x in json.loads(r.stdout)["repos"])
        self.assertEqual(names, sorted(["tab\there", "cr\rhere", "ctlx"]))

    def test_json_with_show_or_limit_is_exit_2(self):
        self.repo("a", {"f.txt": "needle\n"})
        for args in (["--json", "--show"], ["--json", "--show", "--limit", "1"]):
            r = self.scan(*args)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(r.stdout, "")

    def test_json_lists_repositories_that_could_not_be_scanned(self):
        c.make_repo(self.root, {"top.txt": "needle\n"})
        os.makedirs(os.path.join(self.root, 'we"ird', ".git"))
        r = self.scan("--json")
        self.assertEqual(r.returncode, 3)
        data = json.loads(r.stdout)
        self.assertEqual(data["scanned"], 1)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["repos"], [{"repo": ".", "hits": 1}])
        self.assertEqual(len(data["could_not"]), 1)
        self.assertEqual(data["could_not"][0]["repo"], 'we"ird')
        self.assertIn("not a git repository", data["could_not"][0]["reason"])

    # ---- environment --------------------------------------------------------
    def test_the_root_can_come_from_the_environment(self):
        self.repo("a", {"f.txt": "needle\n"})
        r = self.eng("needle", extra={"ROT_RADAR_ROOT": self.root})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(repo_line("a", 1), r.stdout)

    def test_the_root_option_wins_over_the_environment(self):
        self.repo("a", {"f.txt": "needle\n"})
        r = self.eng("needle", "--root", self.root, extra={"ROT_RADAR_ROOT": self.path("nowhere")})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_root_at_all_is_exit_2(self):
        r = self.eng("needle")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertTrue(r.stderr.startswith("rot-radar:"))

    def test_the_rules_folder_comes_from_the_environment_or_sits_beside_the_script(self):
        r = c.engine(["--list"], home=self.home, extra={"ROT_RADAR_RULES": self.rules})
        self.assertEqual(r.stdout, "  needle             [med] a test rule\n")
        r = c.engine(["--list"], home=self.home)
        self.assertIn("silent-stderr", r.stdout)
        self.assertNotIn("needle", r.stdout)

    def test_the_root_may_be_given_with_a_trailing_slash_or_as_a_relative_path(self):
        self.repo("a", {"f.txt": "needle\n"})
        r = self.eng("needle", "--root", self.root + "/")
        self.assertIn(repo_line("a", 1), r.stdout)
        r = self.eng("needle", "--root", ".", cwd=self.root)
        self.assertIn(repo_line("a", 1), r.stdout)

    # ---- --list and help --------------------------------------------------
    def test_list_prints_one_line_per_rule_in_name_order(self):
        rules = c.make_rules(self.path("rules4"), {
            "zeta": c.rule_text(desc="last one", severity="low"),
            "alpha": c.rule_text(desc="first one", severity="high"),
            "Upper": c.rule_text(),
        })
        r = self.eng("--list", rules=rules)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "  alpha              [high] first one\n  zeta               [low] last one\n")

    def test_help(self):
        for flag in ("-h", "--help"):
            r = self.eng(flag)
            self.assertEqual(r.returncode, 0)
            self.assertIn("usage: bash rot-radar.sh", r.stdout)

    # ---- exit codes ---------------------------------------------------------
    def test_exit_0_with_hits(self):
        self.repo("a", {"f.txt": "needle\n"})
        self.assertEqual(self.scan().returncode, 0)

    def test_usage_errors_are_exit_2_with_a_message(self):
        self.repo("a", {"f.txt": "needle\n"})
        cases = {
            "unknown option": ["needle", "--root", self.root, "--bogus"],
            "unknown short option": ["needle", "--root", self.root, "-x"],
            "missing value": ["needle", "--root"],
            "missing value before an option": ["needle", "--root", "--show"],
            "unknown rule": ["nope", "--root", self.root],
            "bad rule name": ["Needle", "--root", self.root],
            "no rule": ["--root", self.root],
            "two rules": ["needle", "needle", "--root", self.root],
        }
        for label, args in cases.items():
            with self.subTest(label):
                r = self.eng(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(r.stdout, "")
                self.assertTrue(r.stderr.startswith("rot-radar:") or "usage" in r.stderr[:20], r.stderr)

    def test_an_unknown_rule_lists_the_known_rules_on_stderr(self):
        r = self.eng("nope", "--root", self.root)
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown rule: nope", r.stderr)
        self.assertIn("needle", r.stderr)

    def test_an_unknown_option_is_never_ignored(self):
        self.repo("a", {"f.txt": "needle\n"})
        r = self.eng("needle", "--root", self.root, "--no-such-option")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--no-such-option", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_a_rule_name_with_a_slash_is_refused(self):
        c.write(os.path.join(self.rules, "sub", "real.rule"), c.rule_text())
        self.repo("a", {"f.txt": "needle\n"})
        r = self.eng("sub/real", "--root", self.root)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")

    def test_scan_failures_are_exit_3(self):
        r = self.eng("needle", "--root", self.path("not-there"))
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        self.assertTrue(r.stderr.startswith("rot-radar:"))
        c.write(self.path("plain-file"), "x")
        r = self.eng("needle", "--root", self.path("plain-file"))
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        os.makedirs(self.path("empty-root"))
        r = self.eng("needle", "--root", self.path("empty-root"))
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        self.assertIn("no git repository", r.stderr)

    def test_a_folder_with_an_empty_git_folder_is_reported_not_counted_twice(self):
        c.make_repo(self.root, {"top.txt": "needle\n", "sub/a.txt": "needle\n"})
        os.makedirs(os.path.join(self.root, "sub", ".git"))
        r = self.scan()
        self.assertEqual(r.returncode, 3, r.stderr)
        expected = (
            "rot-radar: needle [med]\n  a test rule\n  searched: *.txt\n  excluded: (none)\n\n"
            + repo_line(".", 2)
            + "could not scan:\n"
            "  sub: fatal: not a git repository: '.git'\n"
            "TOTAL: 2 hits in 1 of 1 repositories scanned, 1 could not be scanned\n")
        self.assertEqual(r.stdout, expected)
        self.assertIn("rot-radar: sub: fatal: not a git repository", r.stderr)

    def test_one_failing_repository_does_not_stop_the_others(self):
        self.repo("a", {"f.txt": "needle\n"})
        os.makedirs(os.path.join(self.root, "b", ".git"))
        self.repo("c", {"f.txt": "needle\nneedle\n"})
        r = self.scan()
        self.assertEqual(r.returncode, 3)
        self.assertIn(repo_line("c", 2), r.stdout)
        self.assertIn(repo_line("a", 1), r.stdout)
        self.assertIn("TOTAL: 3 hits in 2 of 2 repositories scanned, 1 could not be scanned", r.stdout)

    def test_git_missing_from_path_is_exit_3(self):
        self.repo("a", {"f.txt": "needle\n"})
        bin_dir = self.path("bin")
        os.makedirs(bin_dir)
        for tool in c.TOOLS:
            found = shutil.which(tool)
            self.assertIsNotNone(found, tool)
            os.symlink(found, os.path.join(bin_dir, tool))
        env = c.base_env(self.home)
        env["PATH"] = bin_dir
        env["ROT_RADAR_RULES"] = self.rules
        r = c.run([c.BASH, c.ENGINE, "needle", "--root", self.root], env=env)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertIn("git", r.stderr)
        # Sanity: the same folder of tools plus git works.
        os.symlink(shutil.which("git"), os.path.join(bin_dir, "git"))
        r = c.run([c.BASH, c.ENGINE, "needle", "--root", self.root], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    # ---- rule files are data --------------------------------------------------
    def test_a_rule_file_is_never_run(self):
        marker = self.path("MARKER")
        marker2 = self.path("MARKER2")
        rules = c.make_rules(self.path("rules5"), {
            "sneaky": (
                'RULE_DESC="runs $(touch %s) and `touch %s` and $HOME"\n' % (marker, marker)
                + 'RULE_SEVERITY="low"\nRULE_GLOB="*.txt"\nRULE_PATTERN=\'needle\'\n'),
            "cmdline": "touch %s\n" % marker2 + 'RULE_SEVERITY="low"\n',
        })
        self.repo("a", {"f.txt": "needle\n"})
        r = self.eng("sneaky", "--root", self.root, rules=rules)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("  runs $(touch %s) and `touch %s` and $HOME\n" % (marker, marker), r.stdout)
        r = self.eng("--list", rules=rules)
        self.assertIn("runs $(touch %s)" % marker, r.stdout)
        r = self.eng("cmdline", "--root", self.root, rules=rules)
        self.assertEqual(r.returncode, 2)
        self.assertIn("cmdline.rule", r.stderr)
        self.assertIn("line 1", r.stderr)
        self.assertFalse(os.path.exists(marker))
        self.assertFalse(os.path.exists(marker2))

    def test_rule_file_formats(self):
        text = (
            "# a comment\n"
            "\n"
            "   # an indented comment\n"
            "RULE_DESC=bare words here\n"
            "  RULE_SEVERITY='high'\n"
            'RULE_GLOB="*.txt"\n'
            "RULE_PATTERN='a#b'\n"
            'RULE_FIX_HINT="it\'s a \\n literal"   \n')
        rules = c.make_rules(self.path("rules6"), {"fmt": text})
        self.repo("a", {"f.txt": "xa#by\nno\n"})
        r = self.eng("fmt", "--root", self.root, rules=rules)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("rot-radar: fmt [high]\n  bare words here\n  fix: it's a \\n literal\n", r.stdout)
        self.assertIn(repo_line("a", 1), r.stdout)

    def test_each_rule_file_error_is_exit_2_and_names_the_file(self):
        good = 'RULE_DESC="d"\nRULE_SEVERITY="low"\nRULE_GLOB="*.txt"\nRULE_PATTERN="x"\n'
        bad = {
            "unknown-key": (good + "RULE_TRACKED_ONLY=1\n", "line 5"),
            "no-equals": (good + "just some words\n", "line 5"),
            "open-quote": ('RULE_DESC="d\nRULE_SEVERITY="low"\nRULE_GLOB="*.txt"\nRULE_PATTERN="x"\n', "line 1"),
            "lone-quote": (good + 'RULE_FIX_HINT="\n', "line 5"),
            "mixed-quote": (good + "RULE_FIX_HINT=\"abc'\n", "line 5"),
            "no-pattern": ('RULE_DESC="d"\nRULE_SEVERITY="low"\nRULE_GLOB="*.txt"\n', "RULE_PATTERN"),
            "no-desc": ('RULE_SEVERITY="low"\nRULE_GLOB="*.txt"\nRULE_PATTERN="x"\n', "RULE_DESC"),
            "no-glob": ('RULE_DESC="d"\nRULE_SEVERITY="low"\nRULE_PATTERN="x"\n', "RULE_GLOB"),
            "no-severity": ('RULE_DESC="d"\nRULE_GLOB="*.txt"\nRULE_PATTERN="x"\n', "RULE_SEVERITY"),
            "bad-severity": (good.replace('"low"', '"urgent"'), "RULE_SEVERITY"),
            "empty-pattern": (good.replace('RULE_PATTERN="x"', 'RULE_PATTERN=""'), "RULE_PATTERN"),
            "blank-glob": (good.replace('"*.txt"', '"   "'), "RULE_GLOB"),
        }
        rules = c.make_rules(self.path("rules7"), {k: v[0] for k, v in bad.items()})
        self.repo("a", {"f.txt": "x\n"})
        for name, (_text, where) in bad.items():
            with self.subTest(name):
                r = self.eng(name, "--root", self.root, rules=rules)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(r.stdout, "")
                self.assertIn(name + ".rule", r.stderr)
                self.assertIn(where, r.stderr)
        r = self.eng("--list", rules=rules)
        self.assertEqual(r.returncode, 2)

    @unittest.skipIf(c.is_root(), "root can read a mode 000 file")
    def test_an_unreadable_rule_file_is_exit_2(self):
        self.repo("a", {"f.txt": "needle\n"})
        os.chmod(os.path.join(self.rules, "needle.rule"), 0)
        r = self.scan()
        self.assertEqual(r.returncode, 2)
        self.assertIn("needle.rule", r.stderr)
        os.chmod(os.path.join(self.rules, "needle.rule"), 0o644)

    def test_crlf_rule_files_are_read(self):
        text = c.rule_text().replace("\n", "\r\n")
        rules = c.make_rules(self.path("rules8"), {"needle": text})
        self.repo("a", {"f.txt": "needle\n"})
        r = self.scan(rules=rules)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(repo_line("a", 1), r.stdout)


if __name__ == "__main__":
    unittest.main()
