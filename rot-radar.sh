#!/usr/bin/env bash
# rot-radar.sh - count one known bad pattern across every git repository under a root folder.
#
#   bash rot-radar.sh --list
#   bash rot-radar.sh RULE --root DIR [--repos A,B] [--show] [--limit N] [--json]
#
# One small rule file per pattern (rules/NAME.rule). A rule file is data: it is
# read line by line and never run. Only tracked files are searched, so build
# output and other ignored files do not count. Exit codes:
#   0  every repository found was searched without error (whatever the counts)
#   2  usage or rule error
#   3  the scan could not be completed
# Written for bash 3.2: no mapfile, no associative arrays, and every array that
# can be empty is expanded in the guarded form ${ARR[@]+"${ARR[@]}"}.
set -u

err() { printf 'rot-radar: %s\n' "$*" >&2; }
die2() { err "$*"; exit 2; }
die3() { err "$*"; exit 3; }

usage() {
  printf '%s\n' \
    'usage: bash rot-radar.sh --list' \
    '       bash rot-radar.sh RULE --root DIR [--repos A,B] [--show] [--limit N] [--json]' \
    '' \
    '  --list        list the rules, one line each' \
    '  --root DIR    folder that holds the repositories (or set ROT_RADAR_ROOT)' \
    '  --repos A,B   only these repositories, named by path relative to the root' \
    '  --show        also print every hit under its repository' \
    '  --limit N     with --show, print only the first N hits of each repository' \
    '  --json        print one JSON object instead of text' \
    '  -h, --help    this text' \
    '' \
    'Rules come from rules/ beside this script, or from ROT_RADAR_RULES.' \
    'Repositories are folders with a .git folder at the root or one or two levels below.' \
    'exit 0: every repository was searched; 2: usage or rule error; 3: scan not completed'
}

SELF_DIR=$(cd "$(dirname "$0")" && pwd)
RULES_DIR=${ROT_RADAR_RULES:-$SELF_DIR/rules}

# A rule name is [a-z0-9][a-z0-9-]*; spelled out so the locale cannot widen a range.
valid_name() {
  case $1 in
    ''|-*|*[!abcdefghijklmnopqrstuvwxyz0123456789-]*) return 1 ;;
  esac
  return 0
}

# Names of the rule files in the rules folder, in byte order.
rule_names() {
  local f base
  for f in "$RULES_DIR"/*.rule; do
    [ -f "$f" ] || continue
    base=${f##*/}
    base=${base%.rule}
    valid_name "$base" || continue
    printf '%s\n' "$base"
  done | LC_ALL=C sort
}

# load_rule FILE: read a rule file as data. Sets RULE_DESC, RULE_SEVERITY,
# RULE_GLOB, RULE_PATTERN, RULE_FIX_HINT and RULE_EXCLUDE. On a problem it
# prints one message that names the file (and the line when one line is at
# fault) and returns 1. Nothing in the file is expanded or run: each value is
# copied into a variable as plain text.
load_rule() {
  local file=$1 line trimmed key value n=0 first
  RULE_DESC=""
  RULE_SEVERITY=""
  RULE_GLOB=""
  RULE_PATTERN=""
  RULE_FIX_HINT=""
  RULE_EXCLUDE=""
  if [ ! -f "$file" ] || [ ! -r "$file" ]; then
    err "$file: cannot read the rule file"
    return 1
  fi
  while IFS= read -r line || [ -n "$line" ]; do
    n=$((n + 1))
    line=${line%"${line##*[![:space:]]}"}
    trimmed=${line#"${line%%[![:space:]]*}"}
    case $trimmed in
      ''|'#'*) continue ;;
    esac
    case $trimmed in
      *=*) ;;
      *) err "$file: line $n: expected KEY=value"; return 1 ;;
    esac
    key=${trimmed%%=*}
    value=${trimmed#*=}
    first=${value:0:1}
    if [ "$first" = '"' ] || [ "$first" = "'" ]; then
      if [ "${#value}" -lt 2 ] || [ "${value%"$first"}" = "$value" ]; then
        err "$file: line $n: the value opens with a quote it does not close"
        return 1
      fi
      value=${value#"$first"}
      value=${value%"$first"}
    fi
    case $key in
      RULE_DESC) RULE_DESC=$value ;;
      RULE_SEVERITY) RULE_SEVERITY=$value ;;
      RULE_GLOB) RULE_GLOB=$value ;;
      RULE_PATTERN) RULE_PATTERN=$value ;;
      RULE_FIX_HINT) RULE_FIX_HINT=$value ;;
      RULE_EXCLUDE) RULE_EXCLUDE=$value ;;
      *) err "$file: line $n: unknown key: $key"; return 1 ;;
    esac
  done < "$file"
  for key in RULE_DESC RULE_SEVERITY RULE_GLOB RULE_PATTERN; do
    case $key in
      RULE_DESC) value=$RULE_DESC ;;
      RULE_SEVERITY) value=$RULE_SEVERITY ;;
      RULE_GLOB) value=$RULE_GLOB ;;
      RULE_PATTERN) value=$RULE_PATTERN ;;
    esac
    if [ -z "$value" ]; then
      err "$file: $key is missing or empty"
      return 1
    fi
  done
  case $RULE_SEVERITY in
    high|med|low) ;;
    *) err "$file: RULE_SEVERITY must be high, med or low"; return 1 ;;
  esac
  return 0
}

list_rules() {
  local name rc=0
  while IFS= read -r name; do
    if load_rule "$RULES_DIR/$name.rule"; then
      printf '  %-18s [%s] %s\n' "$name" "$RULE_SEVERITY" "$RULE_DESC"
    else
      printf '  %-18s [%s] %s\n' "$name" "?" "(the rule file has an error, see stderr)"
      rc=2
    fi
  done < <(rule_names)
  return $rc
}

# json_str TEXT: print TEXT as the inside of a JSON string. Backslash, double
# quote, tab, carriage return and newline are escaped; other control
# characters are removed.
json_str() {
  local s=$1 cr tab nl
  case $s in
    *[\\\"[:cntrl:]]*) ;;
    *) printf '%s' "$s"; return ;;
  esac
  cr=$(printf '\r')
  tab=$(printf '\t')
  nl=$(printf '\001')
  printf '%s' "$s" \
    | LC_ALL=C tr -d '\000-\010\013\014\016-\037' \
    | LC_ALL=C tr '\n' '\001' \
    | LC_ALL=C sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e "s/$tab/\\\\t/g" -e "s/$cr/\\\\r/g" -e "s/$nl/\\\\n/g"
}

# ---- arguments ----------------------------------------------------------
RULE_NAME=""
HAVE_RULE=0
ROOT=${ROT_RADAR_ROOT:-}
REPOS_ARG=""
HAVE_REPOS=0
SHOW=0
LIMIT=""
HAVE_LIMIT=0
JSON=0
LIST=0

while [ $# -gt 0 ]; do
  case $1 in
    -h|--help) usage; exit 0 ;;
    --list) LIST=1 ;;
    --show) SHOW=1 ;;
    --json) JSON=1 ;;
    --root|--repos|--limit)
      opt=$1
      if [ $# -lt 2 ]; then die2 "$opt needs a value"; fi
      case $2 in
        --*) die2 "$opt needs a value" ;;
      esac
      case $opt in
        --root) ROOT=$2 ;;
        --repos) REPOS_ARG=$2; HAVE_REPOS=1 ;;
        --limit) LIMIT=$2; HAVE_LIMIT=1 ;;
      esac
      shift
      ;;
    -?*) die2 "unknown option: $1" ;;
    *)
      if [ "$HAVE_RULE" = 1 ]; then die2 "only one rule can be given"; fi
      RULE_NAME=$1
      HAVE_RULE=1
      ;;
  esac
  shift
done

if [ "$LIST" = 1 ]; then
  list_rules
  exit $?
fi

if [ "$HAVE_RULE" = 0 ]; then
  usage >&2
  die2 "no rule given. Known rules: $(rule_names | tr '\n' ' ')"
fi

if [ "$HAVE_LIMIT" = 1 ]; then
  case $LIMIT in
    ''|*[!0123456789]*) die2 "--limit needs a positive whole number" ;;
  esac
  if [ "${#LIMIT}" -gt 9 ] || [ "$((10#$LIMIT))" -lt 1 ]; then
    die2 "--limit needs a positive whole number of at most 9 digits"
  fi
  LIMIT=$((10#$LIMIT))
  if [ "$SHOW" = 0 ]; then die2 "--limit only works together with --show"; fi
fi
if [ "$JSON" = 1 ] && { [ "$SHOW" = 1 ] || [ "$HAVE_LIMIT" = 1 ]; }; then
  die2 "--json cannot be combined with --show or --limit"
fi

if ! valid_name "$RULE_NAME" || [ ! -f "$RULES_DIR/$RULE_NAME.rule" ]; then
  err "unknown rule: $RULE_NAME"
  err "known rules: $(rule_names | tr '\n' ' ')"
  exit 2
fi
load_rule "$RULES_DIR/$RULE_NAME.rule" || exit 2

GLOBS=()
read -r -a GLOBS <<< "$RULE_GLOB"
EXCLUDES=()
read -r -a EXCLUDES <<< "$RULE_EXCLUDE"
if [ "${#GLOBS[@]}" -eq 0 ]; then
  die2 "$RULES_DIR/$RULE_NAME.rule: RULE_GLOB holds no file name pattern"
fi

if [ -z "$ROOT" ]; then
  die2 "no root folder: pass --root DIR or set ROT_RADAR_ROOT"
fi

# ---- the scan -----------------------------------------------------------
if [ ! -d "$ROOT" ]; then
  die3 "the root is missing or is not a folder: $ROOT"
fi
if ! command -v git > /dev/null; then
  die3 "git is not installed (it was not found on PATH)"
fi

case $ROOT in
  -*) ROOT=./$ROOT ;;
esac
while [ "$ROOT" != "/" ] && [ "${ROOT%/}" != "$ROOT" ]; do
  ROOT=${ROOT%/}
done
if [ "$ROOT" = "/" ]; then ROOT_PREFIX=/; else ROOT_PREFIX=$ROOT/; fi

TMP=$(mktemp -d "${TMPDIR:-/tmp}/rot-radar.XXXXXX") || die3 "cannot make a temporary folder"
trap 'rm -rf "$TMP"' EXIT
trap 'exit 3' HUP INT TERM

FIND_FAILED=0
find -H "$ROOT" -maxdepth 3 -name .git -type d > "$TMP/found" || FIND_FAILED=1
sed 's#/\.git$##' "$TMP/found" | LC_ALL=C sort > "$TMP/paths"

REPO_PATH=()
REPO_REL=()
NREPOS=0
while IFS= read -r p; do
  if [ "$p" = "$ROOT" ]; then rel=.; else rel=${p#"$ROOT_PREFIX"}; fi
  REPO_PATH[$NREPOS]=$p
  REPO_REL[$NREPOS]=$rel
  NREPOS=$((NREPOS + 1))
done < "$TMP/paths"

if [ "$NREPOS" -eq 0 ]; then
  if [ "$FIND_FAILED" = 1 ]; then err "some folders under the root could not be read"; fi
  die3 "no git repository found at the root or up to two levels below it: $ROOT"
fi

if [ "$HAVE_REPOS" = 1 ]; then
  WANT=()
  IFS=, read -r -a WANT <<< "$REPOS_ARG"
  if [ "${#WANT[@]}" -eq 0 ]; then die2 "--repos needs at least one repository name"; fi
  for w in ${WANT[@]+"${WANT[@]}"}; do
    known=0
    i=0
    while [ "$i" -lt "$NREPOS" ]; do
      if [ "${REPO_REL[$i]}" = "$w" ]; then known=1; break; fi
      i=$((i + 1))
    done
    if [ "$known" = 0 ]; then die2 "--repos names a repository that was not found: $w"; fi
  done
  KEEP_PATH=()
  KEEP_REL=()
  K=0
  i=0
  while [ "$i" -lt "$NREPOS" ]; do
    for w in ${WANT[@]+"${WANT[@]}"}; do
      if [ "${REPO_REL[$i]}" = "$w" ]; then
        KEEP_PATH[$K]=${REPO_PATH[$i]}
        KEEP_REL[$K]=${REPO_REL[$i]}
        K=$((K + 1))
        break
      fi
    done
    i=$((i + 1))
  done
  REPO_PATH=("${KEEP_PATH[@]}")
  REPO_REL=("${KEEP_REL[@]}")
  NREPOS=$K
fi

PATHSPECS=()
GLOB_TEXT=""
for g in ${GLOBS[@]+"${GLOBS[@]}"}; do
  PATHSPECS[${#PATHSPECS[@]}]=":(glob)**/$g"
  GLOB_TEXT=${GLOB_TEXT:+$GLOB_TEXT }$g
done
EXCL_TEXT=""
for e in ${EXCLUDES[@]+"${EXCLUDES[@]}"}; do
  PATHSPECS[${#PATHSPECS[@]}]=":(exclude,glob)$e"
  EXCL_TEXT=${EXCL_TEXT:+$EXCL_TEXT }$e
done

COUNT=()
FAIL=()
REASON=()
TOTAL=0
HITREPOS=0
SCANNED=0
FAILED=0
i=0
while [ "$i" -lt "$NREPOS" ]; do
  git -C "${REPO_PATH[$i]}" --git-dir=.git grep -nIP -e "$RULE_PATTERN" -- ${PATHSPECS[@]+"${PATHSPECS[@]}"} > "$TMP/out.$i" 2> "$TMP/err.$i"
  rc=$?
  # git's own messages always reach the user.
  while IFS= read -r l || [ -n "$l" ]; do
    err "${REPO_REL[$i]}: $l"
  done < "$TMP/err.$i"
  if [ "$rc" -le 1 ]; then
    n=$(wc -l < "$TMP/out.$i")
    n=$((n + 0))
    COUNT[$i]=$n
    FAIL[$i]=0
    SCANNED=$((SCANNED + 1))
    TOTAL=$((TOTAL + n))
    if [ "$n" -gt 0 ]; then HITREPOS=$((HITREPOS + 1)); fi
  else
    COUNT[$i]=0
    FAIL[$i]=1
    first=""
    IFS= read -r first < "$TMP/err.$i" || true
    if [ -z "$first" ]; then first="git exited with status $rc"; fi
    REASON[$i]=$first
    FAILED=$((FAILED + 1))
  fi
  i=$((i + 1))
done

# ---- output -------------------------------------------------------------
if [ "$JSON" = 1 ]; then
  printf '{"rule":"%s","severity":"%s","scanned":%d,"total":%d,"repos":[' \
    "$(json_str "$RULE_NAME")" "$(json_str "$RULE_SEVERITY")" "$SCANNED" "$TOTAL"
  sep=""
  i=0
  while [ "$i" -lt "$NREPOS" ]; do
    if [ "${FAIL[$i]}" = 0 ]; then
      printf '%s{"repo":"%s","hits":%d}' "$sep" "$(json_str "${REPO_REL[$i]}")" "${COUNT[$i]}"
      sep=,
    fi
    i=$((i + 1))
  done
  printf '],"could_not":['
  sep=""
  i=0
  while [ "$i" -lt "$NREPOS" ]; do
    if [ "${FAIL[$i]}" = 1 ]; then
      printf '%s{"repo":"%s","reason":"%s"}' "$sep" "$(json_str "${REPO_REL[$i]}")" "$(json_str "${REASON[$i]}")"
      sep=,
    fi
    i=$((i + 1))
  done
  printf ']}\n'
else
  printf 'rot-radar: %s [%s]\n' "$RULE_NAME" "$RULE_SEVERITY"
  printf '  %s\n' "$RULE_DESC"
  if [ -n "$RULE_FIX_HINT" ]; then printf '  fix: %s\n' "$RULE_FIX_HINT"; fi
  printf '  searched: %s\n' "$GLOB_TEXT"
  printf '  excluded: %s\n' "${EXCL_TEXT:-(none)}"
  printf '\n'
  : > "$TMP/order"
  i=0
  while [ "$i" -lt "$NREPOS" ]; do
    if [ "${FAIL[$i]}" = 0 ] && [ "${COUNT[$i]}" -gt 0 ]; then
      printf '%010d %010d\n' "$((9999999999 - COUNT[$i]))" "$i" >> "$TMP/order"
    fi
    i=$((i + 1))
  done
  LC_ALL=C sort "$TMP/order" > "$TMP/sorted"
  while read -r _key idx; do
    i=$((10#$idx))
    printf '  %-44s %5d\n' "${REPO_REL[$i]}" "${COUNT[$i]}"
    if [ "$SHOW" = 1 ]; then
      if [ -n "$LIMIT" ]; then
        sed -n "1,${LIMIT}p" "$TMP/out.$i" | sed 's/^/    /'
        if [ "${COUNT[$i]}" -gt "$LIMIT" ]; then
          printf '    (%d more not shown)\n' "$((COUNT[$i] - LIMIT))"
        fi
      else
        sed 's/^/    /' "$TMP/out.$i"
      fi
    fi
  done < "$TMP/sorted"
  if [ "$FAILED" -gt 0 ]; then
    printf 'could not scan:\n'
    i=0
    while [ "$i" -lt "$NREPOS" ]; do
      if [ "${FAIL[$i]}" = 1 ]; then
        printf '  %s: %s\n' "${REPO_REL[$i]}" "${REASON[$i]}"
      fi
      i=$((i + 1))
    done
  fi
  if [ "$FAILED" -gt 0 ]; then
    printf 'TOTAL: %d hits in %d of %d repositories scanned, %d could not be scanned\n' \
      "$TOTAL" "$HITREPOS" "$SCANNED" "$FAILED"
  else
    printf 'TOTAL: %d hits in %d of %d repositories scanned\n' "$TOTAL" "$HITREPOS" "$SCANNED"
  fi
fi

if [ "$FAILED" -gt 0 ] || [ "$FIND_FAILED" = 1 ]; then
  if [ "$FIND_FAILED" = 1 ]; then err "some folders under the root could not be read"; fi
  exit 3
fi
exit 0
