#!/usr/bin/env bash
# rot-radar-report.sh - run every rule through rot-radar.sh and write one dated report.
#
#   bash rot-radar-report.sh --out DIR [--root DIR]
#
# The root also comes from ROT_RADAR_ROOT. The report is DIR/rot-radar-YYYY-MM-DD.md
# (local date); a second run on the same day replaces it. The body holds no time
# of day, so two runs on one day with nothing changed write the same bytes.
# The path of the file is printed on stdout.
# Exit code: the highest exit code any rule run returned (0, 2 or 3); 2 for a
# usage error; 3 when the root is missing or the report cannot be written.
set -u

err() { printf 'rot-radar-report: %s\n' "$*" >&2; }

usage() {
  printf '%s\n' \
    'usage: bash rot-radar-report.sh --out DIR [--root DIR]' \
    '  --out DIR    folder for rot-radar-YYYY-MM-DD.md (created when missing)' \
    '  --root DIR   folder that holds the repositories (or set ROT_RADAR_ROOT)' \
    'Rules come from rules/ beside this script, or from ROT_RADAR_RULES.'
}

SELF_DIR=$(cd "$(dirname "$0")" && pwd)
ENGINE=$SELF_DIR/rot-radar.sh
RULES_DIR=${ROT_RADAR_RULES:-$SELF_DIR/rules}
OUT=""
ROOT=${ROT_RADAR_ROOT:-}

while [ $# -gt 0 ]; do
  case $1 in
    -h|--help) usage; exit 0 ;;
    --out|--root)
      opt=$1
      if [ $# -lt 2 ]; then err "$opt needs a value"; exit 2; fi
      case $2 in
        --*) err "$opt needs a value"; exit 2 ;;
      esac
      if [ "$opt" = "--out" ]; then OUT=$2; else ROOT=$2; fi
      shift
      ;;
    *) err "unknown argument: $1"; usage >&2; exit 2 ;;
  esac
  shift
done

if [ -z "$OUT" ]; then err "no output folder: pass --out DIR"; usage >&2; exit 2; fi
if [ -z "$ROOT" ]; then err "no root folder: pass --root DIR or set ROT_RADAR_ROOT"; exit 2; fi
if [ ! -d "$ROOT" ]; then err "the root is missing or is not a folder: $ROOT"; exit 3; fi

# Rule names: files NAME.rule with NAME matching [a-z0-9][a-z0-9-]*, in byte order.
names=""
for f in "$RULES_DIR"/*.rule; do
  [ -f "$f" ] || continue
  base=${f##*/}
  base=${base%.rule}
  case $base in
    ''|-*|*[!abcdefghijklmnopqrstuvwxyz0123456789-]*) continue ;;
  esac
  names=$names$base$'\n'
done
if [ -z "$names" ]; then err "no rules found in $RULES_DIR"; exit 2; fi
names=$(printf '%s' "$names" | LC_ALL=C sort)

TMP=$(mktemp -d "${TMPDIR:-/tmp}/rot-radar-report.XXXXXX") || { err "cannot make a temporary folder"; exit 3; }
trap 'rm -rf "$TMP"' EXIT
trap 'exit 3' HUP INT TERM

DAY=$(date +%Y-%m-%d)
: > "$TMP/summary"
: > "$TMP/body"
max=0

while IFS= read -r name; do
  "$BASH" "$ENGINE" "$name" --root "$ROOT" > "$TMP/o" 2> "$TMP/e"
  rc=$?
  cat "$TMP/e" >&2
  if [ "$rc" -gt "$max" ]; then max=$rc; fi
  sev=$(sed -n '1s/^rot-radar: [^ ]* \[\(.*\)\]$/\1/p' "$TMP/o")
  total=$(sed -n '/^TOTAL: /p' "$TMP/o")
  if [ -n "$total" ]; then
    printf -- '- %s [%s]: %s\n' "$name" "${sev:-?}" "$total" >> "$TMP/summary"
  else
    msg=$(sed -n 1p "$TMP/e")
    printf -- '- %s [%s]: could not run (exit %d): %s\n' "$name" "${sev:-?}" "$rc" "$msg" >> "$TMP/summary"
  fi
  {
    printf '## %s\n\n' "$name"
    printf '%s\n' '```'
    if [ -s "$TMP/o" ]; then cat "$TMP/o"; else cat "$TMP/e"; fi
    printf '%s\n\n' '```'
  } >> "$TMP/body"
done <<EOF
$names
EOF

mkdir -p "$OUT" || { err "cannot create the output folder: $OUT"; exit 3; }
while [ "$OUT" != "/" ] && [ "${OUT%/}" != "$OUT" ]; do
  OUT=${OUT%/}
done
REPORT=$OUT/rot-radar-$DAY.md
{
  printf '# Rot radar report %s\n\n' "$DAY"
  cat "$TMP/summary"
  printf '\n'
  cat "$TMP/body"
} > "$REPORT" || { err "cannot write $REPORT"; exit 3; }

printf '%s\n' "$REPORT"
exit "$max"
