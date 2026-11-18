#!/usr/bin/env bash
# demo.sh - an offline tour of hunt.sh, rot-radar.sh and rot-radar-report.sh.
#
#   bash examples/demo.sh
#
# Everything happens in a temporary folder made here and removed at the end:
# a folder of five invented cron scripts and two scratch repositories. Nothing
# is written inside this repository and no network is used. Every path in the
# output is relative, so the output is the same on every run.
# Exit code: 0 when every step behaved as expected, 1 otherwise.
set -u

HERE=$(cd "$(dirname "$0")/.." && pwd)
unset ROT_RADAR_ROOT ROT_RADAR_RULES

WORK=$(mktemp -d "${TMPDIR:-/tmp}/rot-radar-demo.XXXXXX") || { echo "demo: cannot make a temporary folder" >&2; exit 1; }
trap 'rm -rf "$WORK"' EXIT
trap 'exit 1' HUP INT TERM

# Keep git independent of the reader's settings, and never need an identity:
# the demo only runs git init and git add, and always names the repository with -C.
mkdir "$WORK/home" "$WORK/data" || exit 1
export HOME="$WORK/home"
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1

BAD=0
STEP_OUT=""
STEP_RC=0

fail() { printf 'demo: unexpected result: %s\n' "$*" >&2; BAD=1; }

# step LABEL COMMAND...: print the command line, run it, print what it wrote.
step() {
  label=$1
  shift
  printf '$ %s\n' "$label"
  STEP_OUT=$("$@" 2>&1)
  STEP_RC=$?
  if [ -n "$STEP_OUT" ]; then printf '%s\n' "$STEP_OUT"; fi
}

expect_in_output() {
  case $STEP_OUT in
    *"$1"*) ;;
    *) fail "the output of the last step does not hold: $1" ;;
  esac
}

# ---- made-up data -----------------------------------------------------------------
data=$WORK/data
mkdir "$data/scripts" "$data/site" "$data/tools" "$data/tools/backup" || exit 1

# Five cron scripts: three throw errors away (one form each), one says what it
# hides, one keeps its errors in a log.
cat > "$data/scripts/backup.sh" <<'EOF'
#!/bin/sh
tar czf "$HOME/backup.tgz" "$HOME/docs" 2>/dev/null
EOF
cat > "$data/scripts/sync.sh" <<'EOF'
#!/bin/sh
rsync -a "$HOME/docs/" "$HOME/mirror/" &>/dev/null
EOF
cat > "$data/scripts/cleanup.sh" <<'EOF'
#!/bin/sh
find "$HOME/tmp" -mtime +7 -delete >/dev/null 2>&1
EOF
cat > "$data/scripts/rotate.sh" <<'EOF'
#!/bin/sh
gzip -f "$HOME/app.log" 2>/dev/null # hides: gzip complains when the log is empty
EOF
cat > "$data/scripts/report.sh" <<'EOF'
#!/bin/sh
mkdir -p "$HOME/logs"
mail-report 2>>"$HOME/logs/report.err"
EOF

write_deploy() {
  # write_deploy [COMMENT]: site/deploy.sh, with a hides comment on its first redirect when given.
  {
    printf '#!/bin/sh\n'
    if [ $# -gt 0 ]; then
      printf 'scp build/* host:/srv 2>/dev/null # hides: %s\n' "$1"
    else
      printf 'scp build/* host:/srv 2>/dev/null\n'
    fi
    printf 'ssh host restart-site\n'
  } > "$data/site/deploy.sh"
}

write_deploy
cat > "$data/site/lint.sh" <<'EOF'
#!/bin/sh
check-style src
EOF
cat > "$data/tools/backup/run.sh" <<'EOF'
#!/bin/sh
dump-database >/dev/null 2>&1
upload-dump 2>>/dev/null
EOF

git -C "$data/site" init -q || exit 1
git -C "$data/site" add -A || exit 1
git -C "$data/tools/backup" init -q || exit 1
git -C "$data/tools/backup" add -A || exit 1

# A file that has a hit but was never added: the engine counts tracked files only.
cat > "$data/site/draft.sh" <<'EOF'
#!/bin/sh
prepare-draft 2>/dev/null
EOF

cd "$data" || exit 1

# ---- the tour ------------------------------------------------------------------------
step "sh hunt.sh scripts" sh "$HERE/hunt.sh" scripts
printf 'exit code: %d\n\n' "$STEP_RC"
if [ "$STEP_RC" -ne 1 ]; then fail "hunt.sh exited $STEP_RC, expected 1"; fi
expect_in_output "3 lines in 3 files throw stderr away"
case $STEP_OUT in
  *rotate.sh*|*report.sh*) fail "hunt.sh listed a script that is exempt or clean" ;;
esac

step "bash rot-radar.sh --list" "$BASH" "$HERE/rot-radar.sh" --list
if [ "$STEP_RC" -ne 0 ]; then fail "--list exited $STEP_RC, expected 0"; fi
expect_in_output "silent-stderr"
expect_in_output "dynamic-code"
printf '\n'

step "bash rot-radar.sh silent-stderr --root . --show" "$BASH" "$HERE/rot-radar.sh" silent-stderr --root . --show
if [ "$STEP_RC" -ne 0 ]; then fail "the first scan exited $STEP_RC, expected 0"; fi
expect_in_output "TOTAL: 3 hits in 2 of 2 repositories scanned"
case $STEP_OUT in
  *draft.sh*) fail "the untracked file was counted" ;;
esac
printf '\n'

printf '# add a "# hides:" comment to the redirect in site/deploy.sh\n'
write_deploy "scp prints a host key notice on every run"
printf '\n'

step "bash rot-radar.sh silent-stderr --root . --show" "$BASH" "$HERE/rot-radar.sh" silent-stderr --root . --show
if [ "$STEP_RC" -ne 0 ]; then fail "the second scan exited $STEP_RC, expected 0"; fi
expect_in_output "TOTAL: 2 hits in 1 of 2 repositories scanned"
printf '\n'

# The report file name holds today's date; show it as YYYY-MM-DD so the output never changes.
printf '$ bash rot-radar-report.sh --root . --out reports\n'
STEP_OUT=$("$BASH" "$HERE/rot-radar-report.sh" --root . --out reports 2>&1)
STEP_RC=$?
printf '%s\n' "$STEP_OUT" | sed 's/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/YYYY-MM-DD/'
if [ "$STEP_RC" -ne 0 ]; then fail "the report exited $STEP_RC, expected 0"; fi
printf '\n'

printf '%s\n' "\$ grep '^- ' reports/rot-radar-*.md"
files=$(ls reports)
case $files in
  rot-radar-*.md) ;;
  *) fail "the report file was not written" ;;
esac
summary=$(grep '^- ' reports/rot-radar-*.md)
printf '%s\n' "$summary"
case $summary in
  *"- silent-stderr [high]: TOTAL: 2 hits in 1 of 2 repositories scanned"*) ;;
  *) fail "the report summary does not show the silent-stderr total" ;;
esac

cd / || exit 1
if [ "$BAD" -ne 0 ]; then
  echo "demo: a step did not behave as expected" >&2
  exit 1
fi
printf '\ndemo finished: every step behaved as expected\n'
exit 0
