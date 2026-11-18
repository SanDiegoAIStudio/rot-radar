"""Mutation run: break the code on purpose and check that the tests notice.

    /usr/bin/python3 tests/mutate.py

Each mutation is a text replacement in a fresh temporary copy of the repository.
The copy holds only an allowlist of top-level names. The test suite then runs in
that copy. A mutation the suite fails on is "killed"; one the suite passes is a
"survivor" and means a test is missing. A mutation whose old text is not found
exactly once stops the run with an error, so a mutation list that has drifted
from the code cannot pass in silence.

Output: one line per mutation, then
    mutations: N, killed: K, survived: S, skipped: P
Exit code: 0 when nothing survived, 1 when something survived, 2 when the run
itself could not be done (a bad mutation, or the unmodified copy fails).
"""
import concurrent.futures
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Only these top-level names are copied into the scratch copies.
ALLOW = ["hunt.sh", "rot-radar.sh", "rot-radar-report.sh", "rules", "examples",
         "tests", "README.md", "LICENSE", ".gitignore"]

TIMEOUT = 900
WORKERS = 6

HUNT = "hunt.sh"
ENGINE = "rot-radar.sh"
REPORT = "rot-radar-report.sh"


def rule(name):
    return "rules/%s.rule" % name


# Each mutation: (name, [(file, old text, new text), ...]). Every old text must
# occur exactly once in its file. A mutation may instead carry a function that
# takes the file text and returns the changed text: (name, [(file, function)]).
MUTATIONS = [
    # ---- hunt.sh -----------------------------------------------------------
    ("hunt: the hides exemption is dropped", [(HUNT,
        'n=$(grep -vcE -e "$exempt" "$tmp/hits")',
        'n=$(grep -cE -e "$forms" "$tmp/hits")')]),
    ("hunt: an empty hides comment exempts the line", [(HUNT,
        "exempt='#[[:space:]]*hides:[[:space:]]*[^[:space:]]'",
        "exempt='#[[:space:]]*hides:'")]),
    ("hunt: binary files are searched", [
        (HUNT, 'grep -IlE -e "$forms"', 'grep -alE -e "$forms"'),
        (HUNT, 'grep -IE -e "$forms" -- "$f"', 'grep -aE -e "$forms" -- "$f"')]),
    ("hunt: a missing folder gives a zero count and exit 0", [(HUNT,
        "  printf 'hunt: not a folder: %s\\n' \"$dir\" >&2\n  exit 2",
        "  printf '0 lines in 0 files throw stderr away\\n'\n  exit 0")]),
    ("hunt: a grep error is ignored", [(HUNT,
        'if [ -s "$tmp/err" ]; then', 'if false; then')]),
    ("hunt: the errors-only form is left out", [(HUNT,
        "forms='2>>?[[:space:]]*/dev/null|&>>?", "forms='&>>?")]),
    ("hunt: the both-streams form is left out", [(HUNT,
        "|&>>?[[:space:]]*/dev/null|>>?", "|>>?")]),
    ("hunt: the output-then-errors form is left out", [(HUNT,
        "/dev/null|>>?[[:space:]]*/dev/null[[:space:]]+2>&1'", "/dev/null'")]),
    ("hunt: the >> variant is left out", [(HUNT, "forms='2>>?", "forms='2>")]),
    ("hunt: exit 0 with lines found", [(HUNT,
        'if [ "$lines" -gt 0 ]; then\n  exit 1\nfi',
        'if [ "$lines" -gt 0 ]; then\n  exit 0\nfi')]),
    ("hunt: a name is cut at its first colon", [(HUNT,
        "printf '%s\\n' \"$f\" >> \"$tmp/found\"",
        "printf '%s\\n' \"${f%%:*}\" >> \"$tmp/found\"")]),
    ("hunt: the file list is sorted in reverse", [(HUNT,
        'sort "$tmp/found"', 'sort -r "$tmp/found"')]),
    ("hunt: the count adds one per file, not per line", [(HUNT,
        "lines=$((lines + n))", "lines=$((lines + 1))")]),
    ("hunt: the default folder is misspelled", [(HUNT,
        "dir=${1-${HOME-}/scripts}", "dir=${1-${HOME-}/script}")]),
    ("hunt: a linked folder given as the argument is not followed", [(HUNT,
        'find -H "$dir" -type f', 'find "$dir" -type f')]),
    ("hunt: extra arguments are accepted", [(HUNT,
        'if [ "$#" -gt 1 ]; then', 'if false; then')]),

    # ---- rot-radar.sh --------------------------------------------------------
    ("engine: the rule file is loaded with source", [(ENGINE,
        'load_rule "$RULES_DIR/$RULE_NAME.rule" || exit 2',
        '. "$RULES_DIR/$RULE_NAME.rule" || exit 2')]),
    ("engine: an unknown key is accepted", [(ENGINE,
        '*) err "$file: line $n: unknown key: $key"; return 1 ;;', '*) ;;')]),
    ("engine: a bad severity is accepted", [(ENGINE,
        '*) err "$file: RULE_SEVERITY must be high, med or low"; return 1 ;;', '*) ;;')]),
    ("engine: a missing pattern is accepted", [(ENGINE,
        "for key in RULE_DESC RULE_SEVERITY RULE_GLOB RULE_PATTERN; do",
        "for key in RULE_DESC RULE_SEVERITY RULE_GLOB; do")]),
    ("engine: untracked files are searched", [(ENGINE,
        "grep -nIP -e", "grep --untracked -nIP -e")]),
    ("engine: binary files are searched", [(ENGINE, "grep -nIP -e", "grep -nP -e")]),
    ("engine: a git failure counts as zero hits", [(ENGINE,
        'if [ "$rc" -le 1 ]; then', "if true; then")]),
    ("engine: exit 0 with a repository that could not be scanned", [(ENGINE,
        'if [ "$FAILED" -gt 0 ] || [ "$FIND_FAILED" = 1 ]; then',
        'if [ "$FIND_FAILED" = 1 ]; then')]),
    ("engine: exit 0 with no repository found", [(ENGINE,
        '  die3 "no git repository found at the root or up to two levels below it: $ROOT"',
        '  err "no git repository found at the root or up to two levels below it: $ROOT"\n  exit 0')]),
    ("engine: exit 0 with a missing root", [(ENGINE,
        '  die3 "the root is missing or is not a folder: $ROOT"',
        '  err "the root is missing or is not a folder: $ROOT"\n  exit 0')]),
    ("engine: the search depth is one level less", [(ENGINE,
        "-maxdepth 3", "-maxdepth 2")]),
    ("engine: --git-dir=.git is dropped", [(ENGINE,
        "--git-dir=.git grep", "grep")]),
    ("engine: excludes are ignored", [(ENGINE,
        'PATHSPECS[${#PATHSPECS[@]}]=":(exclude,glob)$e"', ":")]),
    ("engine: excludes are not printed", [(ENGINE,
        "printf '  excluded: %s\\n' \"${EXCL_TEXT:-(none)}\"",
        "printf '  excluded: %s\\n' \"(none)\"")]),
    ("engine: an unknown --repos name is ignored", [(ENGINE,
        'if [ "$known" = 0 ]; then die2', "if false; then die2")]),
    ("engine: an unknown option is ignored", [(ENGINE,
        '-?*) die2 "unknown option: $1" ;;', "-?*) ;;")]),
    ("engine: --limit is not applied", [(ENGINE,
        'if [ -n "$LIMIT" ]; then', "if false; then")]),
    ("engine: JSON strings are not escaped", [(ENGINE,
        '    *[\\\\\\"[:cntrl:]]*) ;;',
        "    *) printf '%s' \"$s\"; return ;;")]),
    ("engine: JSON leaves out repositories with zero hits", [(ENGINE,
        'if [ "${FAIL[$i]}" = 0 ]; then\n      printf \'%s{"repo"',
        'if [ "${FAIL[$i]}" = 0 ] && [ "${COUNT[$i]}" -gt 0 ]; then\n      printf \'%s{"repo"')]),
    ("engine: repository lines are ordered by path only", [(ENGINE,
        "printf '%010d %010d\\n' \"$((9999999999 - COUNT[$i]))\" \"$i\"",
        "printf '%010d %010d\\n' 0 \"$i\"")]),
    ("engine: a rule name holding a slash or capitals is accepted", [(ENGINE,
        "''|-*|*[!abcdefghijklmnopqrstuvwxyz0123456789-]*) return 1 ;;",
        "''|-*) return 1 ;;")]),
    ("engine: the total adds one per repository, not per hit", [(ENGINE,
        "TOTAL=$((TOTAL + n))", "TOTAL=$((TOTAL + 1))")]),
    ("engine: the root is not read from the environment", [(ENGINE,
        "ROOT=${ROT_RADAR_ROOT:-}", "ROOT=")]),
    ("engine: the rules folder is not read from the environment", [(ENGINE,
        "RULES_DIR=${ROT_RADAR_RULES:-$SELF_DIR/rules}", "RULES_DIR=$SELF_DIR/rules")]),
    ("engine: git's own error output is thrown away", [(ENGINE,
        '2> "$TMP/err.$i"', "2> /dev/null")]),
    ("engine: the empty-array guard is removed", [(ENGINE, "GUARD", "GUARD")]),

    # ---- rules ---------------------------------------------------------------
    ("rule silent-stderr: the exemption is dropped", [(rule("silent-stderr"),
        "(?!.*#[ \\t]*hides:[ \\t]*\\S)", "(?!zzzz)")]),
    ("rule silent-stderr: the gap after hides: may cross a line break", [(rule("silent-stderr"),
        "hides:[ \\t]*\\S", "hides:\\s*\\S")]),
    ("rule dynamic-code: the leading class is dropped", [(rule("dynamic-code"),
        "(^|[^.$[:alnum:]_])(eval|exec)\\(", "(eval|exec)\\(")]),
    ("rule home-path-leak: only one folder name matches", [(rule("home-path-leak"),
        "(Users|home)", "(Users)")]),
    ("rule silent-catch-js: a catch with no binding is not counted", [(rule("silent-catch-js"),
        "(\\([^)]*\\))?", "\\([^)]*\\)")]),
    ("rule silent-catch-js: a name that ends in catch counts", [(rule("silent-catch-js"),
        "'\\bcatch", "'catch")]),

    # ---- rot-radar-report.sh -------------------------------------------------
    ("report: a rule that could not run is left out and the exit code is 0", [
        (REPORT, "    printf -- '- %s [%s]: could not run (exit %d): %s\\n' "
                 "\"$name\" \"${sev:-?}\" \"$rc\" \"$msg\" >> \"$TMP/summary\"", "    :"),
        (REPORT, '  if [ "$rc" -gt "$max" ]; then max=$rc; fi', "  :")]),
    ("report: the --out folder is ignored", [(REPORT,
        "REPORT=$OUT/rot-radar-$DAY.md", "REPORT=./rot-radar-$DAY.md")]),
    ("report: a missing root does not stop the report", [(REPORT,
        'if [ ! -d "$ROOT" ]; then err "the root is missing or is not a folder: $ROOT"; exit 3; fi',
        ":")]),
]

GUARD_NAME = "engine: the empty-array guard is removed"
GUARD_RE = re.compile(r'\$\{(\w+)\[@\]\+"\$\{\1\[@\]\}"\}')


def bash_is_new():
    """True when /bin/bash is 4.4 or newer, where an empty array under set -u is fine."""
    try:
        out = subprocess.run(
            ["/bin/bash", "-c", 'echo "${BASH_VERSINFO[0]} ${BASH_VERSINFO[1]}"'],
            stdout=subprocess.PIPE, universal_newlines=True, timeout=30).stdout.split()
        return (int(out[0]), int(out[1])) >= (4, 4)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return False


def copy_repo(dest):
    for name in ALLOW:
        src = os.path.join(REPO, name)
        if not os.path.exists(src):
            continue
        target = os.path.join(dest, name)
        if os.path.isdir(src):
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, target)


def apply_edits(dest, name, edits):
    for rel, old, new in edits:
        path = os.path.join(dest, rel)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if name == GUARD_NAME:
            changed = GUARD_RE.sub(lambda m: '"${%s[@]}"' % m.group(1), text)
        else:
            if text.count(old) != 1:
                raise SystemExit("mutate: bad mutation %r: the text to replace occurs %d times in %s: %r"
                                 % (name, text.count(old), rel, old))
            changed = text.replace(old, new)
        if changed == text:
            raise SystemExit("mutate: mutation %r did not change %s" % (name, rel))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(changed)


def run_suite(cwd):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        r = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-f"],
            cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, errors="replace", timeout=TIMEOUT)
        return r.returncode, r.stdout
    except subprocess.TimeoutExpired:
        return 1, "timed out after %d seconds" % TIMEOUT


def run_one(name, edits):
    with tempfile.TemporaryDirectory(prefix="rr-mutant-") as td:
        copy_repo(td)
        apply_edits(td, name, edits)
        rc, out = run_suite(td)
    return rc, out


def validate():
    """Check every mutation against the real files; list all that no longer apply."""
    bad = []
    for name, edits in MUTATIONS:
        if name == GUARD_NAME:
            with open(os.path.join(REPO, ENGINE), encoding="utf-8") as fh:
                if not GUARD_RE.search(fh.read()):
                    bad.append("%s: no guarded empty-array expansion found" % name)
            continue
        for rel, old, new in edits:
            with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                n = fh.read().count(old)
            if n != 1:
                bad.append("%s: %d matches in %s for %r" % (name, n, rel, old))
            elif old == new:
                bad.append("%s: replacement equals the original" % name)
    return bad


def main():
    bad = validate()
    if bad:
        print("mutate: these mutations no longer match the code:")
        for line in bad:
            print("  " + line)
        return 2
    # The unmodified copy must pass, or every mutation would look killed.
    with tempfile.TemporaryDirectory(prefix="rr-mutant-") as td:
        copy_repo(td)
        rc, out = run_suite(td)
    if rc != 0:
        print("mutate: the unmodified copy fails its own tests:")
        print("\n".join(out.splitlines()[-25:]))
        return 2

    skip_guard = bash_is_new()
    jobs = []
    skipped = []
    for name, edits in MUTATIONS:
        if name == GUARD_NAME and skip_guard:
            skipped.append(name)
            continue
        jobs.append((name, edits))

    killed = survived = 0
    survivors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [(name, pool.submit(run_one, name, edits)) for name, edits in jobs]
        for name, fut in futures:
            rc, out = fut.result()
            if rc != 0:
                killed += 1
                print("killed   %s" % name)
            else:
                survived += 1
                survivors.append(name)
                print("survived %s" % name)
            sys.stdout.flush()
    for name in skipped:
        print("skipped  %s (/bin/bash is 4.4 or newer, where an empty array under set -u is not an error)" % name)
    print("mutations: %d, killed: %d, survived: %d, skipped: %d"
          % (len(jobs) + len(skipped), killed, survived, len(skipped)))
    if survivors:
        print("A survivor means a missing test: add one that fails for that change.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
