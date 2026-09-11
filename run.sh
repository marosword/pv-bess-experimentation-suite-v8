#!/bin/sh
set -eu

root=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
parent=$(dirname "$root")
package=$(basename "$root")
output="$root/output"
workers=4 #change, machine dependent
smoke=

while [ "$#" -gt 0 ]; do
    case "$1" in
        --output)
            output=${2:?missing output path}; shift 2 ;;
        --workers)
            workers=${2:?missing worker count}; shift 2 ;;
        --smoke)
            smoke=--smoke; shift ;;
        *)
            echo "usage: $0 [--output PATH] [--workers N] [--smoke]" >&2; exit 2 ;;
    esac
done

case "$workers" in
    ''|*[!0-9]*) echo "--workers must be a positive integer" >&2; exit 2 ;;
esac
[ "$workers" -gt 0 ] || { echo "--workers must be a positive integer" >&2; exit 2; }
[ -z "$smoke" ] || workers=1

if [ -n "${PYTHON:-}" ]; then
    python=$PYTHON
elif [ -x "$parent/.venv/bin/python" ]; then
    python="$parent/.venv/bin/python"
else
    python=python3
fi

export PYTHONHASHSEED=0
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export TZ=UTC
export LC_ALL=C
export LANG=C
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$root:$parent${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$output"
logs="$output/logs"
mkdir -p "$logs"

pids=
index=0
while [ "$index" -lt "$workers" ]; do
    tag=$(printf '%03d' "$index")
    "$python" -m "$package.runner" \
        --input-declaration "$root/input/povelce_2015_2019_v10.json" \
        --output "$output" \
        --shard-count "$workers" \
        --shard-index "$index" \
        --families all $smoke >"$logs/shard_$tag.log" 2>&1 &
    pids="$pids $!"
    index=$((index + 1))
done

failed=0
for pid in $pids; do
    if ! wait "$pid"; then
        failed=1
    fi
done

[ "$failed" -eq 0 ] || { echo "experiment failed; see $logs" >&2; exit 1; }
echo "experiment complete: $output"
