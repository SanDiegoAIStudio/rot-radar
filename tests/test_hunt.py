"""Tests for hunt.sh, each case under /bin/sh, /bin/bash and dash when installed."""
import os
import shutil
import unittest

import _common as c

TAIL = "throw stderr away"


def count_line(lines, files):
    return "%d lines in %d files %s" % (lines, files, TAIL)


class HuntTest(c.Scratch):
    def hunt(self, shell, *args, cwd=None, extra=None):
        return c.run([shell, c.HUNT] + list(args), cwd=cwd, home=self.home, extra=extra)

    def folder(self, files):
        self._count = getattr(self, "_count", 0) + 1
        d = self.path("scripts-%d" % self._count)
        os.makedirs(d)
        for name, content in files.items():
            c.write(os.path.join(d, name), content, binary=isinstance(content, bytes))
        return d

    def assert_hunt(self, shell, d, out_files, lines, rc):
        r = self.hunt(shell, d)
        expected = "".join(f + "\n" for f in out_files) + count_line(lines, len(out_files)) + "\n"
        self.assertEqual(r.stdout, expected, shell)
        self.assertEqual(r.returncode, rc, shell + " " + r.stderr)
        return r

    # ---- what counts ----------------------------------------------------
    def test_each_form_is_counted(self):
        forms = [
            "cmd 2>/dev/null",
            "cmd 2>>/dev/null",
            "cmd &>/dev/null",
            "cmd &>>/dev/null",
            "cmd >/dev/null 2>&1",
            "cmd >>/dev/null 2>&1",
            "cmd 2> /dev/null",
            "cmd 2>>   /dev/null",
            "cmd > /dev/null 2>&1",
            "cmd >>  /dev/null   2>&1",
        ]
        for shell in c.shells():
            for form in forms:
                with self.subTest(shell=shell, form=form):
                    d = self.folder({"a.sh": "#!/bin/sh\n" + form + "\n"})
                    self.assert_hunt(shell, d, [os.path.join(d, "a.sh")], 1, 1)

    def test_forms_that_keep_errors_are_not_counted(self):
        clean = [
            "cmd 2>&1 >/dev/null",
            "cmd >/dev/null",
            "cmd >>/dev/null",
            "cmd 2>>\"$LOG\"",
            "cmd 2>&1",
            "cmd </dev/null",
            "echo /dev/null",
        ]
        for shell in c.shells():
            for form in clean:
                with self.subTest(shell=shell, form=form):
                    d = self.folder({"a.sh": "#!/bin/sh\n" + form + "\n"})
                    self.assert_hunt(shell, d, [], 0, 0)

    def test_a_comment_that_says_what_is_hidden_exempts_the_line(self):
        for shell in c.shells():
            for form in ("cmd 2>/dev/null # hides: tar warns about changing files",
                         "cmd &>/dev/null #hides:x",
                         "cmd >/dev/null 2>&1   #   hides:   reason here"):
                with self.subTest(shell=shell, form=form):
                    d = self.folder({"a.sh": form + "\n"})
                    self.assert_hunt(shell, d, [], 0, 0)

    def test_an_empty_hides_comment_exempts_nothing(self):
        for shell in c.shells():
            for form in ("cmd 2>/dev/null # hides:", "cmd 2>/dev/null # hides:    "):
                with self.subTest(shell=shell, form=form):
                    d = self.folder({"a.sh": form + "\n"})
                    self.assert_hunt(shell, d, [os.path.join(d, "a.sh")], 1, 1)

    def test_exemption_covers_only_its_own_line(self):
        for shell in c.shells():
            with self.subTest(shell=shell):
                d = self.folder({"a.sh": "cmd 2>/dev/null # hides: noise\nother 2>/dev/null\n"})
                self.assert_hunt(shell, d, [os.path.join(d, "a.sh")], 1, 1)

    def test_binary_files_are_skipped(self):
        for shell in c.shells():
            with self.subTest(shell=shell):
                d = self.folder({"blob.bin": b"\x00\x01\x02 cmd 2>/dev/null\n"})
                self.assert_hunt(shell, d, [], 0, 0)

    def test_a_redirect_inside_a_comment_or_string_counts(self):
        for shell in c.shells():
            with self.subTest(shell=shell):
                d = self.folder({"a.sh": "# remember: do not use 2>/dev/null\necho 'x 2>/dev/null'\n"})
                self.assert_hunt(shell, d, [os.path.join(d, "a.sh")], 2, 1)

    def test_files_in_nested_folders_are_searched(self):
        for shell in c.shells():
            with self.subTest(shell=shell):
                d = self.folder({"x/y/z/deep.sh": "cmd 2>/dev/null\n"})
                self.assert_hunt(shell, d, [os.path.join(d, "x", "y", "z", "deep.sh")], 1, 1)

    def test_a_link_to_a_folder_inside_the_folder_is_not_followed_but_a_linked_folder_argument_is(self):
        outside = self.path("outside")
        c.write(os.path.join(outside, "a.sh"), "cmd 2>/dev/null\n")
        d = self.folder({"b.sh": "echo hi\n"})
        link = os.path.join(d, "linked")
        os.symlink(outside, link)
        top = self.path("top-link")
        os.symlink(outside, top)
        for shell in c.shells():
            with self.subTest(shell=shell):
                self.assert_hunt(shell, d, [], 0, 0)
                self.assert_hunt(shell, top, [os.path.join(top, "a.sh")], 1, 1)

    # ---- names, counts and order ------------------------------------------
    def test_names_with_a_space_or_a_colon_are_printed_whole_and_counted_once(self):
        names = ["has space.sh", "has:colon.sh", "odd: 12: name.sh"]
        for shell in c.shells():
            with self.subTest(shell=shell):
                d = self.folder({n: "cmd 2>/dev/null\n" for n in names})
                expected = sorted(os.path.join(d, n) for n in names)
                self.assert_hunt(shell, d, expected, 3, 1)

    def test_count_line_for_zero_one_and_several(self):
        for shell in c.shells():
            with self.subTest(shell=shell):
                d = self.folder({"a.sh": "echo hi\n"})
                r = self.hunt(shell, d)
                self.assertEqual(r.stdout, "0 lines in 0 files throw stderr away\n")
                self.assertEqual(r.returncode, 0)
                c.write(os.path.join(d, "b.sh"), "x 2>/dev/null\n")
                r = self.hunt(shell, d)
                self.assertEqual(r.stdout, "%s\n1 lines in 1 files throw stderr away\n" % os.path.join(d, "b.sh"))
                self.assertEqual(r.returncode, 1)
                c.write(os.path.join(d, "c.sh"), "x 2>/dev/null\ny &>/dev/null\nz >/dev/null 2>&1\n")
                r = self.hunt(shell, d)
                self.assertEqual(
                    r.stdout,
                    "%s\n%s\n4 lines in 2 files throw stderr away\n" % (os.path.join(d, "b.sh"), os.path.join(d, "c.sh")))
                self.assertEqual(r.returncode, 1)

    def test_files_are_sorted_in_byte_order(self):
        for shell in c.shells():
            with self.subTest(shell=shell):
                d = self.folder({n: "cmd 2>/dev/null\n" for n in ["m.sh", "a.sh", "Z.sh", "B.sh", "y.sh"]})
                r = self.hunt(shell, d)
                got = r.stdout.splitlines()[:-1]
                self.assertEqual(got, [os.path.join(d, n) for n in ["B.sh", "Z.sh", "a.sh", "m.sh", "y.sh"]])

    # ---- exit codes and errors --------------------------------------------
    def test_a_missing_folder_is_exit_2_with_a_message_and_nothing_on_stdout(self):
        for shell in c.shells():
            with self.subTest(shell=shell):
                r = self.hunt(shell, self.path("no-such-folder"))
                self.assertEqual(r.returncode, 2)
                self.assertEqual(r.stdout, "")
                self.assertIn("no-such-folder", r.stderr)

    def test_a_file_instead_of_a_folder_is_exit_2(self):
        for shell in c.shells():
            with self.subTest(shell=shell):
                c.write(self.path("plain.sh"), "cmd 2>/dev/null\n")
                r = self.hunt(shell, self.path("plain.sh"))
                self.assertEqual(r.returncode, 2)
                self.assertEqual(r.stdout, "")
                self.assertNotEqual(r.stderr, "")

    def test_too_many_arguments_is_exit_2(self):
        r = self.hunt(c.SH, self.tmp, self.tmp)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")

    def test_help_is_exit_0(self):
        r = self.hunt(c.SH, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage: sh hunt.sh", r.stdout)

    @unittest.skipIf(c.is_root(), "root can read a mode 000 file")
    def test_an_unreadable_file_is_exit_2_and_the_rest_is_still_reported(self):
        for shell in c.shells():
            with self.subTest(shell=shell):
                d = self.folder({"good.sh": "cmd 2>/dev/null\n", "locked.sh": "cmd 2>/dev/null\n"})
                os.chmod(os.path.join(d, "locked.sh"), 0)
                r = self.hunt(shell, d)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(
                    r.stdout, "%s\n1 lines in 1 files throw stderr away\n" % os.path.join(d, "good.sh"))
                self.assertIn("locked.sh", r.stderr)
                self.assertIn("floor", r.stderr)
                os.chmod(os.path.join(d, "locked.sh"), 0o644)

    # ---- defaults ---------------------------------------------------------
    def test_the_default_folder_is_home_scripts(self):
        for shell in c.shells():
            with self.subTest(shell=shell):
                c.write(os.path.join(self.home, "scripts", "job.sh"), "cmd 2>/dev/null\n")
                r = self.hunt(shell, cwd=self.tmp)
                self.assertEqual(
                    r.stdout,
                    "%s\n1 lines in 1 files throw stderr away\n" % os.path.join(self.home, "scripts", "job.sh"))
                self.assertEqual(r.returncode, 1)

    def test_the_default_folder_missing_is_exit_2(self):
        r = self.hunt(c.SH, cwd=self.tmp)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")

    # ---- the shipped scripts pass their own check ---------------------------
    def test_the_shipped_scripts_throw_nothing_away(self):
        for shell in c.shells():
            with self.subTest(shell=shell):
                d = self.path("copies-" + os.path.basename(shell))
                os.makedirs(d)
                for name in ("hunt.sh", "rot-radar.sh", "rot-radar-report.sh"):
                    shutil.copy(os.path.join(c.REPO, name), os.path.join(d, name))
                r = self.hunt(shell, d)
                self.assertEqual(r.stdout, "0 lines in 0 files throw stderr away\n")
                self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
