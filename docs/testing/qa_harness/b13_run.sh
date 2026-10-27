#!/usr/bin/env bash
# B13 targeted batch runner: resource gates + `ISOLATION PROVED` + pytest on the disposable stack b13-20261026a.
#   [NEGCTL=a,b] b13_run.sh <batch-name> <pytest args...>   evidence -> docs/testing/qa_evidence_b13/<batch-name>.{log,isolation.txt,resources.txt}
# `PYTHONPATH=/qa/b13:/qa/b12` is set inside the runner so `-p negctl13` / `-p negctl` resolve; NEGCTL (if set) is forwarded.
set -uo pipefail
RUN=b13-20261026a
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"; REPO="$(cd "$HERE/../../.." && pwd -P)"
EV="$REPO/docs/testing/qa_evidence_b13"; BATCH="$1"; shift
free_kb=$(df --output=avail -k / | tail -1 | tr -d ' ')
{ echo "== resources $(date -u +%FT%TZ)"; df -h / | tail -1; free -m | sed -n 1,3p; docker stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}' 2>/dev/null | grep "qa-$RUN" ; } > "$EV/$BATCH.resources.txt"
[[ $free_kb -ge $((2*1024*1024)) ]] || { echo "STOP: root free < 2 GiB"; exit 3; }
bash "$HERE/stack.sh" guard $RUN > "$EV/$BATCH.isolation.txt" 2>&1
grep -qx 'ISOLATION PROVED' "$EV/$BATCH.isolation.txt" || { echo "STOP: isolation not proved"; cat "$EV/$BATCH.isolation.txt"; exit 3; }
echo ISOLATION PROVED
xenv="$(mktemp)"; chmod 600 "$xenv"; { echo "PYTHONPATH=/qa/b13:/qa/b12"; [[ -n "${NEGCTL:-}" ]] && echo "NEGCTL=$NEGCTL"; } > "$xenv"
QA_EXTRA_ENV="$xenv" bash "$HERE/stack.sh" pytest $RUN "$@" > "$EV/$BATCH.log" 2>&1; rc=$?
rm -f "$xenv"
df -h / | tail -1 >> "$EV/$BATCH.resources.txt"
tail -15 "$EV/$BATCH.log"; echo "rc=$rc"; exit $rc
