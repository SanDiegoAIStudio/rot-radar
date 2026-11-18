#!/bin/sh
# hunt.sh - list the scripts under a folder that throw error output away.
#
# usage: sh hunt.sh [DIR]        (DIR defaults to $HOME/scripts)
#
# A line counts when it sends error output to the null device in one of three
# forms: errors only, both streams, or output first and then errors pointed at
# the same place. A line is exempt when it carries a comment that starts with
# "hides:" and names what the redirect hides, because that is a decision
# somebody wrote down. The script reads lines of text; it does not parse shell,
# so a redirect inside a comment or a string counts like any other.
#
# stdout: each file with at least one counted line (sorted), then one last line
#         "N lines in M files throw stderr away".
# exit:   0 nothing found, 1 something found, 2 the hunt could not be completed.

LC_ALL=C
export LC_ALL

forms='2>>?[[:space:]]*/dev/null|&>>?[[:space:]]*/dev/null|>>?[[:space:]]*/dev/null[[:space:]]+2>&1'
exempt='#[[:space:]]*hides:[[:space:]]*[^[:space:]]'

usage() {
  printf '%s\n' 'usage: sh hunt.sh [DIR]' \
    '  Lists every file under DIR (default $HOME/scripts) that has a line sending' \
    '  error output to the null device without a "# hides: reason" comment.' \
    '  exit 0: nothing found, 1: something found, 2: the hunt could not be completed'
}

case ${1-} in
  -h|--help) usage; exit 0 ;;
esac
if [ "$#" -gt 1 ]; then
  usage >&2
  exit 2
fi

dir=${1-${HOME-}/scripts}
case $dir in
  -*) dir=./$dir ;;
esac

if [ ! -d "$dir" ]; then
  printf 'hunt: not a folder: %s\n' "$dir" >&2
  exit 2
fi

tmp=$(mktemp -d "${TMPDIR:-/tmp}/hunt.XXXXXX") || {
  printf 'hunt: cannot make a temporary folder\n' >&2
  exit 2
}
trap 'rm -rf "$tmp"' EXIT
trap 'exit 2' HUP INT TERM

incomplete=0

# Pass 1: one search over the whole tree for files with a line in one of the
# three forms. Binary files are skipped. Anything either program says on stderr
# means some file or folder could not be read; it is shown and remembered.
find -H "$dir" -type f -exec grep -IlE -e "$forms" -- {} + > "$tmp/candidates" 2> "$tmp/err"
if [ -s "$tmp/err" ]; then
  cat "$tmp/err" >&2
  incomplete=1
fi

# Pass 2: per candidate, count the lines that are not exempt.
lines=0
files=0
: > "$tmp/found"
while IFS= read -r f; do
  grep -IE -e "$forms" -- "$f" > "$tmp/hits" 2> "$tmp/err"
  rc=$?
  if [ "$rc" -gt 1 ]; then
    cat "$tmp/err" >&2
    incomplete=1
    continue
  fi
  n=$(grep -vcE -e "$exempt" "$tmp/hits")
  if [ "${n:-0}" -gt 0 ]; then
    lines=$((lines + n))
    files=$((files + 1))
    printf '%s\n' "$f" >> "$tmp/found"
  fi
done < "$tmp/candidates"

sort "$tmp/found"
printf '%s lines in %s files throw stderr away\n' "$lines" "$files"

if [ "$incomplete" -ne 0 ]; then
  printf 'hunt: some files could not be read, so the count above is a floor\n' >&2
  exit 2
fi
if [ "$lines" -gt 0 ]; then
  exit 1
fi
exit 0
