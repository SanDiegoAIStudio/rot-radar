# rot-radar

Two small tools for finding code that fails quietly. `hunt.sh` is a ten-minute hunt: it lists every script in a folder that throws its error output away, so a scheduled job that has been failing in silence gets found. `rot-radar.sh` is the same idea at scale: it counts one known bad pattern across every git repository under a root folder, one small rule file per pattern, and `rot-radar-report.sh` writes a dated report over every rule. They are for anyone who keeps a folder of cron or launchd scripts, or a few dozen repositories, and wants to know where errors are being swallowed.

Everything is plain shell. The tools need only sh, bash, git, grep, find, sort, sed, tr, wc, cut, mktemp, date, mkdir, cat, rm, dirname and printf. Nothing is installed and no network is used.

## What you get

The hunt lists each script with at least one counted line and ends with a count line. This is the output of `sh hunt.sh scripts` from `bash examples/demo.sh`, run on five invented cron scripts:

```
$ sh hunt.sh scripts
scripts/backup.sh
scripts/cleanup.sh
scripts/sync.sh
3 lines in 3 files throw stderr away
exit code: 1
```

The engine counts one pattern in every repository under a root, one line per repository that has hits. This is `bash rot-radar.sh silent-stderr --root . --show` from the same demo, run over two scratch repositories:

```
$ bash rot-radar.sh silent-stderr --root . --show
rot-radar: silent-stderr [high]
  Shell lines that send error output to the null device without a '# hides:' comment
  fix: log the output to a file someone reads, or end the line with a comment that starts '# hides:' and names what it hides
  searched: *.sh *.bash *.zsh *.ksh *.cron *.crontab crontab
  excluded: (none)

  tools/backup                                     2
    run.sh:2:dump-database >/dev/null 2>&1
    run.sh:3:upload-dump 2>>/dev/null
  site                                             1
    deploy.sh:2:scp build/* host:/srv 2>/dev/null
TOTAL: 3 hits in 2 of 2 repositories scanned
```

## Quick start

Clone or download this repository, change into its folder, and run the demo:

```
bash examples/demo.sh
```

The demo builds a folder of made-up data in a temporary folder, runs the tools on it, prints each command line before its output, and removes the folder at the end. It writes nothing inside this repository and exits 0 when every step behaved as expected. Its output, in order:

1. `sh hunt.sh scripts` lists the three invented scripts that throw errors away, one per form, and exits 1. A fourth script carries a `# hides:` comment and a fifth logs its errors, so neither is listed.
2. `bash rot-radar.sh --list` shows the seven rules, with severity and description.
3. `bash rot-radar.sh silent-stderr --root . --show` counts the same pattern in two scratch repositories: 3 hits in 2 of 2. A file in one repository that was never added to git is not counted.
4. The demo adds a `# hides:` comment to one counted line and runs the scan again: 2 hits in 1 of 2. The count falls because that line now says what it hides.
5. `bash rot-radar-report.sh --root . --out reports` writes a dated report and prints its path, and the demo prints the summary lines of that report. The file name holds today's date; the demo shows it as `YYYY-MM-DD` so its output is the same on every run.

To point the hunt at your own folder:

```
sh hunt.sh "$HOME/scripts"
```

## The ten-minute hunt

```
sh hunt.sh DIR
```

DIR defaults to `$HOME/scripts`. The hunt searches every file under DIR, recursively, skips binary files, and counts a line that throws error output away in one of three forms. This is the grep expression it uses, shown once:

```
2>>?[[:space:]]*/dev/null|&>>?[[:space:]]*/dev/null|>>?[[:space:]]*/dev/null[[:space:]]+2>&1
```

- `cmd 2>/dev/null` sends only errors to the null device.
- `cmd &>/dev/null` sends both streams there.
- `cmd >/dev/null 2>&1` sends the output there first and then points errors at it.

The `>>` variants of each are counted too. `cmd 2>&1 >/dev/null` is not counted, because it keeps the errors, and neither is a plain `cmd >/dev/null`.

A line is exempt when it carries a comment that says what the redirect hides. The comment must match `#[[:space:]]*hides:[[:space:]]*[^[:space:]]`, so `# hides: tar warns when a file changes while it is read` exempts the line and an empty `# hides:` exempts nothing.

The output is each file that has at least one counted line, one path per line as grep prints it (the DIR prefix included), sorted in byte order, and then one last line, exactly `N lines in M files throw stderr away`. With nothing found the only line is `0 lines in 0 files throw stderr away`.

Exit codes: 0 when no line was found, 1 when at least one was found, 2 when the hunt could not be completed. Exit 2 means DIR is missing or is not a folder (a message on stderr, nothing on stdout), or grep reported an error such as a file it could not read. In the second case the files and the count line are still printed, followed by a stderr line saying the count is a floor because some files could not be read.

Two more places to look on macOS, where scheduled jobs live outside your scripts folder:

```
crontab -l | grep -n '/dev/null'
grep -l '/dev/null' ~/Library/LaunchAgents/*.plist
```

### Sort the hits into three piles

Read each hit and put it in one of three piles:

1. A real failure that was hidden. The command fails now and nobody knew.
2. Expected noise. The command prints something harmless on every run, such as a warning you have decided to live with.
3. Unknown. You cannot tell what the redirect hides.

For piles one and three, log the output to a file you will read instead of discarding it:

```
mkdir -p "$HOME/logs"
my-sync-command 2>>"$HOME/logs/my-sync.err"
```

A log nobody reads hides a failure as well as the null device does. Put the log where something will look at it: a scheduled check that fails when the file is not empty, or an alert on its size.

For pile two, keep the redirect and say why. The rule:

> Every redirect of errors to the null device in a scheduled job carries a comment at the end of its line that starts `# hides:` and names what it hides. When that comment cannot be written, the output is logged instead.

`hunt.sh` exits 0 only when every such line carries its comment, which makes the rule something a schedule or a commit check can enforce:

```
sh hunt.sh "$HOME/scripts" > /dev/null || echo "a script throws its errors away"
```

## Count one pattern across every repository

```
bash rot-radar.sh --list
bash rot-radar.sh RULE --root DIR [--repos A,B] [--show] [--limit N] [--json]
bash rot-radar.sh -h
```

- `--list` prints one line per rule in name order and needs no root.
- `RULE` is the name of a file `RULE.rule` in the rules folder. A name that is not lowercase letters, digits and hyphens, or that has no file, is an error that prints the known rules on stderr.
- `--root DIR` is the folder that holds the repositories. It can also come from the environment variable `ROT_RADAR_ROOT`. With neither, the engine exits 2.
- `--repos A,B` keeps only the repositories with exactly those paths relative to the root. A name that matches none is an error.
- `--show` prints every hit under its repository as `path:line:text`.
- `--limit N` (a positive whole number of up to nine digits, only valid with `--show`) prints the first N hits of each repository and then `(K more not shown)` when hits were left out.
- `--json` prints one JSON object on one line and nothing else. It cannot be combined with `--show` or `--limit`.
- `-h` or `--help` prints the usage and exits 0.

The rules folder is `rules/` beside the script, or the folder named by `ROT_RADAR_RULES`.

A repository is any folder that holds a `.git` folder, at the root itself or one or two levels below it. It is named by its path relative to the root, and the root itself is `.`. The engine searches tracked files only, with the pattern as a Perl-compatible regular expression: `git -C REPO --git-dir=.git grep -nIP -e PATTERN -- PATHSPECS`.

Text output, in order: a header with the rule name and severity; the description, the fix hint, the file patterns searched and the folders excluded; a blank line; one line per repository that has hits, ordered by count from high to low and then by path; a line `could not scan:` with one `PATH: REASON` line each when a repository failed; and a last line `TOTAL: T hits in H of S repositories scanned`, with `, C could not be scanned` added when C is above 0. T is the sum of the counts, H the repositories with at least one hit, and S the repositories searched without error.

Without `--show` the same scan prints only the counts. This is `bash rot-radar.sh silent-stderr --root .` in the demo's data:

```
$ bash rot-radar.sh silent-stderr --root .
rot-radar: silent-stderr [high]
  Shell lines that send error output to the null device without a '# hides:' comment
  fix: log the output to a file someone reads, or end the line with a comment that starts '# hides:' and names what it hides
  searched: *.sh *.bash *.zsh *.ksh *.cron *.crontab crontab
  excluded: (none)

  tools/backup                                     2
  site                                             1
TOTAL: 3 hits in 2 of 2 repositories scanned
```

With `--show --limit 1`, each repository shows its first hit and a line for the rest:

```
$ bash rot-radar.sh silent-stderr --root . --show --limit 1
  tools/backup                                     2
    run.sh:2:dump-database >/dev/null 2>&1
    (1 more not shown)
  site                                             1
    deploy.sh:2:scp build/* host:/srv 2>/dev/null
TOTAL: 3 hits in 2 of 2 repositories scanned
```

(The header lines are the same as above and are left out here.)

### JSON

`--json` prints this shape. It is the output of `bash rot-radar.sh silent-stderr --root . --json` in the demo's data, on one line:

```
{"rule":"silent-stderr","severity":"high","scanned":2,"total":3,"repos":[{"repo":"site","hits":1},{"repo":"tools/backup","hits":2}],"could_not":[]}
```

`repos` lists every repository searched without error, zeros included, in path order. `could_not` lists `{"repo": PATH, "reason": TEXT}` for each repository that failed. Every string is escaped so that a JSON parser reads it back exactly: backslash, double quote, tab, carriage return and newline are escaped and other control characters are removed.

### Exit codes

- 0: at least one repository was found and every repository found was searched without error, whatever the counts.
- 2: a usage or rule error: an unknown option, a missing value, an unknown rule, a bad rule file, an unknown `--repos` name, or no root given.
- 3: the scan could not be completed: the root is missing or is not a folder, no repository was found under it, git is not installed, or any repository failed. The rest are still reported and the output is still printed.

Messages go to stderr and start with `rot-radar:`. If one repository cannot be searched, git's first line of error output is printed in the `could not scan:` list as the reason, and the others are still searched. The engine never prints a zero for a repository it could not scan.

The engine exits 0 with hits where the hunt exits 1. A count above zero is the normal state while a pattern is being worked down, so read the total, and watch it fall over time.

## The rules

| Rule | Severity | What it finds | File patterns |
|---|---|---|---|
| silent-stderr | high | Shell lines that send error output to the null device without a `# hides:` comment (the same three forms and exemption as `hunt.sh`) | `*.sh *.bash *.zsh *.ksh *.cron *.crontab crontab` |
| dynamic-code | high | Calls to `eval(` or `exec(`, which run text as code. Method calls such as `regex.exec(` and names such as `my_exec(` do not count | `*.py *.ts *.tsx *.js *.jsx` |
| bare-except | high | Python bare `except:` clauses, which swallow every error including Ctrl-C | `*.py` |
| silent-catch-js | high | Empty catch blocks in JavaScript and TypeScript, with a binding such as `catch (e) {}` or without one, `catch {}` | `*.ts *.tsx *.js *.jsx` |
| home-path-leak | high | Absolute home folder paths on macOS and Linux committed to the repository | `*.md *.ts *.tsx *.js *.jsx *.json *.py *.sh *.yml *.yaml *.toml` |
| ts-any | med | TypeScript `: any` annotations, which switch off type checking | `*.ts *.tsx` |
| console-log | low | `console.log` and `console.debug` calls left in JavaScript and TypeScript | `*.ts *.tsx *.js *.jsx` |

A file pattern such as `crontab` matches at any depth: `crontab` and `etc/crontab` both count.

## Write your own rule

A rule is a file named `NAME.rule` in the rules folder, where NAME is lowercase letters, digits and hyphens and starts with a letter or digit. A rule file is data: the engine reads it line by line and never runs it. A `$(...)` or a backtick inside a value is text, not a command.

Format: blank lines and lines whose first non-space character is `#` are skipped. Every other line is `KEY=value`, where the value is bare, or wrapped in one pair of double quotes, or wrapped in one pair of single quotes. The outer pair is removed and everything between is taken literally: no escapes, no expansion, and a `#` inside a value is part of the value. A repeated key takes the last value.

| Key | Required | Meaning |
|---|---|---|
| `RULE_DESC` | yes | What the rule finds, in one line |
| `RULE_SEVERITY` | yes | `high`, `med` or `low` |
| `RULE_GLOB` | yes | Space-separated file name patterns such as `*.sh crontab`; each one matches at any depth |
| `RULE_PATTERN` | yes | A Perl-compatible regular expression; it cannot be empty |
| `RULE_FIX_HINT` | no | What to do about a hit |
| `RULE_EXCLUDE` | no | Space-separated pathspec globs relative to each repository's top folder, such as `vendor/**` or `**/fixtures/**` |

An unknown key, a line that is not `KEY=value`, a value that opens with a quote it does not close, a missing required key, or a severity outside the three is exit 2, with a message that names the file and, where one line is at fault, its line number. A glob or an exclude cannot hold a space.

A worked example, for a rule this repository does not ship: find a `breakpoint()` call left in Python files. Save this as `my-rules/breakpoint-call.rule`:

```
RULE_DESC="Python code that stops in the debugger"
RULE_SEVERITY=med
RULE_GLOB="*.py"
RULE_PATTERN="^[ \t]*breakpoint\(\)"
RULE_FIX_HINT="Delete the call before it is committed."
```

Then run it:

```
ROT_RADAR_RULES=my-rules bash rot-radar.sh breakpoint-call --root . --show
```

Run over a scratch folder with one tracked Python file that calls `breakpoint()`, this printed:

```
rot-radar: breakpoint-call [med]
  Python code that stops in the debugger
  fix: Delete the call before it is committed.
  searched: *.py
  excluded: (none)

  py                                               1
    calc.py:2:    breakpoint()
TOTAL: 1 hits in 1 of 3 repositories scanned
```

The same folder also held the two demo repositories, which is why the total reads 1 of 3.

## Run the report on a schedule

```
bash rot-radar-report.sh --out DIR [--root DIR]
```

The root can also come from `ROT_RADAR_ROOT`. The report runs every rule through `rot-radar.sh` and writes `DIR/rot-radar-YYYY-MM-DD.md` with the local date. It creates DIR when it is missing, replaces that day's file when it exists, and prints the path of the file it wrote. The body is a `# Rot radar report YYYY-MM-DD` heading, a summary list with one line per rule (the rule name and severity followed by that rule's TOTAL line, or `could not run (exit N):` and the first line of the engine's message), and then a `## NAME` heading with the engine's text output in a fenced block for each rule. There is no time of day anywhere in the body, so two runs on one day with nothing changed write the same bytes.

The exit code is the highest exit code any rule run returned (0, 2 or 3), and 2 for its own usage errors (no `--out`, no root). A root that is missing stops the report before anything is written, with exit 3.

One cron line that runs it every Monday at 07:00 and appends both streams to a log file:

```
0 7 * * 1 bash /path/to/rot-radar/rot-radar-report.sh --root "$HOME/code" --out "$HOME/rot-reports" >> "$HOME/logs/rot-radar.log" 2>&1
```

The `.gitignore` in this repository keeps report files out of version control.

## Tests

From the repository folder:

```
/usr/bin/python3 -m unittest discover -s tests
/usr/bin/python3 tests/mutate.py
```

The first command runs 109 unit tests with the Python standard library, driving the scripts through `subprocess` in scratch folders under the system temporary directory. It took about 20 seconds here. The hunt tests run under `/bin/sh`, `/bin/bash` and `dash` when it is installed. Every git call in a test names its target with `-C` and uses only `git init -q` and `git add`, so no identity is needed and no repository setting of yours can change a result.

The second command is a mutation run. It makes 51 deliberate breakages of the code, one at a time, each a text replacement in a fresh temporary copy of the repository, and runs the unit tests in each copy. A breakage the tests fail on is `killed`; one they pass on is a `survived` and means a test is missing. The last run killed all 51 and left none surviving, and the run prints `mutations: N, killed: K, survived: S, skipped: P` at the end and exits 1 if anything survived. The mutations include dropping the `# hides:` exemption, loading a rule file with `source`, searching untracked files, counting a git failure as zero hits, leaving JSON strings unescaped, and removing the guard for empty arrays. That last one can only be killed by a bash older than 4.4; where `/bin/bash` is 4.4 or newer it is printed as `skipped` with that reason.

## Limits

Only what is true of this folder as tested:

- Tracked files only. The engine searches what git knows, so a new file counts once it is added with `git add`. Ignored and untracked files are not searched.
- The engine needs a git built with Perl-compatible regular expressions. When it is absent, git says so in its own message, and the engine reports that repository under `could not scan` with that message as the reason.
- Two levels of depth. A repository three levels below the root is not found.
- Worktrees and submodules, whose `.git` is a file rather than a folder, are not found.
- Every rule matches within one line. An empty catch block whose braces sit on two lines, or any other pattern split across lines, is not counted.
- The home-path-leak rule matches its pattern, `/(Users|home)/` followed by one folder name and a slash, anywhere in a line. A web route of that shape in a JavaScript file counts as well, even though it is not a folder on disk.
- The hunt reads lines, not shell. A redirect inside a comment or a string counts like any other, which is why `examples/demo.sh` in this repository shows up when you hunt it.
- Scripts with no file extension are searched by the hunt but not by the silent-stderr rule, unless you add their names to its globs. The rule's globs name `crontab` and nothing else without an extension.
- A folder or file name that holds a newline is not supported.
- A folder inside the hunted folder that is a symbolic link is not followed (the hunt lists regular files only). A symbolic link given as the DIR argument itself is followed. This was observed with the BSD grep and find on the machine below and is pinned by a test; other versions of grep and find were not tried.
- Tested on macOS (Darwin 27.2.0, arm64) with GNU bash 3.2.57 as both `/bin/bash` and `/bin/sh`, `dash` from `/bin/dash`, git 2.54.0 (Apple Git-157), BSD grep 2.6.0 (FreeBSD) and Python 3.9.6. Not tested: Linux, GNU grep, busybox, bash 4 or 5, a git built without Perl-compatible expressions, and Windows.

## License

MIT. See `LICENSE`.

## Built at San Diego AI Studio

This tool comes out of San Diego AI Studio, the builders' community in San Diego, where builders show the systems they run. More projects: https://sandiegoaistudio.com/projects
