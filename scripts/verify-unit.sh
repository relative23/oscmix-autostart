#!/bin/sh
# Run `systemd-analyze verify` on the unit and fail on anything it says.
#
# Roadmap item J. tests/test_unit_file.py reads the unit as text: it
# catches the directives known to break a *user* unit, and it asserts the
# timing budget against the constants. What it cannot catch is a typo in
# a directive *name* -- systemd ignores unknown keys, so
# `NoNewPrivilegs=yes` silently disables the hardening it looks like it
# enables, and every string-matching test still passes.
#
# systemd-analyze knows the key names. It does not, however, exit
# non-zero for them: an unknown key is reported on stderr and the exit
# status stays 0. So the gate is the output, not the status -- and only
# the lines about *this* unit, because the tool also reports on whatever
# else is installed on the machine running it.
#
# --user matters: the unit is a user unit, and the specifiers (%h) and
# the permitted directives differ from the system manager's.

set -eu

UNIT="${1:-$(dirname "$0")/../systemd/oscmix.service}"

if ! command -v systemd-analyze >/dev/null 2>&1; then
    echo "verify-unit: systemd-analyze not found; skipping" >&2
    exit 77
fi

if [ ! -f "$UNIT" ]; then
    echo "verify-unit: no such unit: $UNIT" >&2
    exit 1
fi

BASENAME="$(basename "$UNIT")"
OUTPUT="$(systemd-analyze verify --user "$UNIT" 2>&1 || true)"

# Anything naming our unit is a finding: unknown keys, bad values,
# unresolvable specifiers. Other units on the host are not our problem.
FINDINGS="$(printf '%s\n' "$OUTPUT" | grep -F "$BASENAME" || true)"

if [ -n "$FINDINGS" ]; then
    echo "systemd-analyze rejected $BASENAME:" >&2
    printf '%s\n' "$FINDINGS" >&2
    exit 1
fi

echo "systemd-analyze verify: $BASENAME is clean"
