"""Tests for the seven shipped rule files, run through the real engine."""
import os
import re
import unittest

import _common as c

RULE_NAMES = ["bare-except", "console-log", "dynamic-code", "home-path-leak",
              "silent-catch-js", "silent-stderr", "ts-any"]


class RuleTest(c.Scratch):
    def setUp(self):
        super().setUp()
        self.root = self.path("root")
        os.makedirs(self.root)
        self._n = 0

    def hits(self, rule, files):
        """Scan one fresh repository holding files; return the sorted 'path:line' hits."""
        self._n += 1
        c.make_repo(os.path.join(self.root, "r%d" % self._n), files)
        r = c.engine([rule, "--root", os.path.join(self.root, "r%d" % self._n), "--show"],
                     home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = []
        for line in r.stdout.splitlines():
            if line.startswith("    ") and not line.startswith("     ") and "more not shown" not in line:
                m = re.match(r"    (.*?):(\d+):", line)
                self.assertIsNotNone(m, line)
                out.append("%s:%s" % (m.group(1), m.group(2)))
        return sorted(out)

    def check(self, rule, name, counted, not_counted):
        """Lines in counted must each be hit; lines in not_counted must not be."""
        body = "".join(line + "\n" for line in counted + not_counted)
        got = self.hits(rule, {name: body})
        expected = sorted("%s:%d" % (name, i + 1) for i in range(len(counted)))
        self.assertEqual(got, expected, "counted=%r not_counted=%r" % (counted, not_counted))

    # ---- silent-stderr --------------------------------------------------------
    def test_silent_stderr_forms(self):
        self.check("silent-stderr", "job.sh", [
            "cmd 2>/dev/null",
            "cmd 2>>/dev/null",
            "cmd &>/dev/null",
            "cmd &>>/dev/null",
            "cmd >/dev/null 2>&1",
            "cmd >>/dev/null 2>&1",
            "cmd 2> /dev/null",
            "cmd >  /dev/null   2>&1",
            "# note: 2>/dev/null",
        ], [
            "cmd 2>&1 >/dev/null",
            "cmd >/dev/null",
            "cmd 2>>\"$LOG\"",
            "cmd 2>&1",
            "cmd </dev/null",
        ])

    def test_silent_stderr_exemption_and_the_empty_comment(self):
        self.check("silent-stderr", "job.sh", [
            "cmd 2>/dev/null # hides:",
            "cmd 2>/dev/null # hides:    ",
            "cmd 2>/dev/null # hide: typo",
            "cmd 2>/dev/null # hides",
        ], [
            "cmd 2>/dev/null # hides: tar warns about changing files",
            "cmd &>/dev/null #hides:x",
            "cmd >/dev/null 2>&1   #   hides:   reason here",
            "# hides: before it\ncmd 2>/dev/null # hides: after",
        ])

    def test_silent_stderr_never_reads_across_a_line_break(self):
        body = ("cmd 2>\n/dev/null\n"
                "cmd >\n/dev/null\n2>&1\n"
                "cmd 2>/dev/null # hides:\nnext line\n"
                "cmd 2>/dev/null # hides:  \t\n\treason on the next line\n")
        self.assertEqual(self.hits("silent-stderr", {"a.sh": body}), ["a.sh:6", "a.sh:8"])

    def test_bare_except_reports_the_line_it_is_on(self):
        body = "x = 1\n\n\n    \nexcept:\n    pass\n"
        self.assertEqual(self.hits("bare-except", {"m.py": body}), ["m.py:5"])

    def test_silent_stderr_exemption_is_per_line(self):
        got = self.hits("silent-stderr", {
            "a.sh": "x 2>/dev/null # hides: noise\ny 2>/dev/null\n"})
        self.assertEqual(got, ["a.sh:2"])

    def test_silent_stderr_globs(self):
        line = "cmd 2>/dev/null\n"
        files = {
            "a.sh": line, "b.bash": line, "c.zsh": line, "d.ksh": line,
            "e.cron": line, "f.crontab": line, "crontab": line,
            "etc/crontab": line, "deep/er/x.sh": line,
            "notes.txt": line, "deploy": line, "z.py": line,
        }
        got = self.hits("silent-stderr", files)
        want = sorted("%s:1" % n for n in [
            "a.sh", "b.bash", "c.zsh", "d.ksh", "e.cron", "f.crontab", "crontab",
            "etc/crontab", "deep/er/x.sh"])
        self.assertEqual(got, want)

    def test_silent_stderr_agrees_with_the_hunt_line_for_line(self):
        lines = [
            "cmd 2>/dev/null", "cmd &>>/dev/null", "cmd >>/dev/null 2>&1",
            "cmd 2>&1 >/dev/null", "cmd >/dev/null", "cmd 2>/dev/null # hides: x",
            "cmd 2>/dev/null # hides:", "plain line", "echo '2>/dev/null'",
        ]
        body = "".join(line + "\n" for line in lines)
        d = self.path("hunt-dir")
        c.write(os.path.join(d, "a.sh"), body)
        h = c.run([c.SH, c.HUNT, d], home=self.home)
        m = re.match(r"(?s).*?(\d+) lines in", h.stdout)
        self.assertIsNotNone(m, h.stdout)
        self.assertEqual(len(self.hits("silent-stderr", {"a.sh": body})), int(m.group(1)))

    # ---- dynamic-code ---------------------------------------------------------
    def test_dynamic_code(self):
        self.check("dynamic-code", "m.py", [
            "x = eval(text)",
            "exec(code)",
            "    result = exec(code, ns)",
            "y = (eval(text))",
            "z = a+eval(text)",
        ], [
            "m = pattern.exec(text)",
            "my_exec(code)",
            "do_eval(code)",
            "$eval(code)",
            "evaluate(code)",
            "obj.eval(code)",
            "executor(code)",
        ])

    def test_dynamic_code_globs(self):
        line = "eval(x)\n"
        files = {"a.py": line, "b.ts": line, "c.tsx": line, "d.js": line, "e.jsx": line,
                 "f.sh": line, "g.md": line, "sub/h.py": line}
        self.assertEqual(self.hits("dynamic-code", files),
                         sorted("%s:1" % n for n in ["a.py", "b.ts", "c.tsx", "d.js", "e.jsx", "sub/h.py"]))

    # ---- home-path-leak -------------------------------------------------------
    def test_home_path_leak_counts_both_folder_names(self):
        sl = "/"
        mac = sl + "Users" + sl + "alice" + sl + "project"
        lin = sl + "home" + sl + "bob.smith" + sl + "bin"
        self.check("home-path-leak", "doc.md", [
            "see " + mac,
            "cd " + lin,
            "x=\"" + sl + "Users" + sl + "a_b-c.d" + sl + "\"",
        ], [
            "use $HOME/scripts",
            "the Users folder",
            sl + "Users" + sl,
            sl + "homes" + sl + "alice" + sl + "x",
            "~/scripts",
        ])

    def test_home_path_leak_globs(self):
        text = "p = " + "/" + "home" + "/" + "dev" + "/" + "x\n"
        files = {n: text for n in ["a.md", "b.ts", "c.tsx", "d.js", "e.jsx", "f.json", "g.py",
                                   "h.sh", "i.yml", "j.yaml", "k.toml", "l.txt", "m.rb"]}
        self.assertEqual(
            self.hits("home-path-leak", files),
            sorted("%s:1" % n for n in ["a.md", "b.ts", "c.tsx", "d.js", "e.jsx", "f.json",
                                        "g.py", "h.sh", "i.yml", "j.yaml", "k.toml"]))

    # ---- bare-except ----------------------------------------------------------
    def test_bare_except(self):
        self.check("bare-except", "m.py", [
            "except:",
            "    except:",
            "\texcept :",
            "  except  :  # comment",
        ], [
            "except ValueError:",
            "except (A, B):",
            "except Exception as e:",
            "x = 'except:'",
            "# except:",
        ])

    # ---- silent-catch-js --------------------------------------------------------
    def test_silent_catch_js(self):
        self.check("silent-catch-js", "m.ts", [
            "try { f(); } catch (e) {}",
            "try { f(); } catch(e){ }",
            "} catch (err) {   }",
            "try { f(); } catch (e: unknown) {}",
            "try { f(); } catch {}",
            "} catch{ }",
        ], [
            "try { f(); } catch (e) { log(e); }",
            "} catch (e) {",
            "catchAll(e) {}",
            "mycatch {}",
            "p.catch(() => {})",
            "} catch { log(); }",
        ])

    # ---- console-log ------------------------------------------------------------
    def test_console_log(self):
        self.check("console-log", "m.js", [
            "console.log('x');",
            "  console.debug(value)",
            "if (a) console.log(b)",
        ], [
            "console.error('x');",
            "console.warn('x');",
            "console.info('x');",
            "logger.log('x');",
            "console.logger('x');",
        ])

    # ---- ts-any -----------------------------------------------------------------
    def test_ts_any(self):
        self.check("ts-any", "m.ts", [
            "let x: any = 1;",
            "function f(a:any) {}",
            "const y :   any[] = [];",
        ], [
            "let x: anything = 1;",
            "let x: unknown = 1;",
            "// many things",
            "const company = 1;",
        ])

    def test_ts_any_is_not_searched_in_plain_javascript(self):
        self.assertEqual(self.hits("ts-any", {"a.js": "let x: any = 1;\n"}), [])

    # ---- every shipped rule -------------------------------------------------------
    def test_every_shipped_rule_parses_and_is_listed(self):
        files = sorted(f for f in os.listdir(c.RULES) if f.endswith(".rule"))
        self.assertEqual(files, [n + ".rule" for n in RULE_NAMES])
        r = c.engine(["--list"], home=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 7)
        for name, line in zip(RULE_NAMES, lines):
            self.assertRegex(line, r"^  %s +\[(high|med|low)\] \S" % re.escape(name))

    def test_every_shipped_rule_runs_clean_on_an_empty_repository(self):
        c.make_repo(os.path.join(self.root, "empty"), {"readme.txt": "nothing\n"})
        for name in RULE_NAMES:
            with self.subTest(rule=name):
                r = c.engine([name, "--root", self.root], home=self.home)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("TOTAL: 0 hits in 0 of 1 repositories scanned\n", r.stdout)

    def test_shipped_rules_carry_the_values_the_interface_names(self):
        def val(rule, key):
            with open(os.path.join(c.RULES, rule + ".rule")) as fh:
                for line in fh:
                    if line.startswith(key + "="):
                        return line.rstrip("\n")[len(key) + 2:-1]
            return None
        self.assertEqual(val("silent-stderr", "RULE_SEVERITY"), "high")
        self.assertEqual(val("dynamic-code", "RULE_SEVERITY"), "high")
        self.assertEqual(val("silent-stderr", "RULE_GLOB"),
                         "*.sh *.bash *.zsh *.ksh *.cron *.crontab crontab")
        self.assertEqual(val("dynamic-code", "RULE_GLOB"), "*.py *.ts *.tsx *.js *.jsx")
        self.assertEqual(val("home-path-leak", "RULE_PATTERN"), "/(Users|home)/[A-Za-z0-9._-]+/")


if __name__ == "__main__":
    unittest.main()
