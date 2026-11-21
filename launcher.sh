#!/usr/bin/env bash
set -uo pipefail
umask 077

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 1
log_dir="${HOME}/.config/ippon/logs"
mkdir -p -- "$log_dir" || exit 1
log_file="$(mktemp "$log_dir/ippon-$(date +%Y%m%d-%H%M%S).log.XXXXXX")" || exit 1
ln -sfn -- "$(basename -- "$log_file")" "$log_dir/latest.log" || exit 1

printf 'Started: %s\nProject: %s\nLog: %s\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$project_dir" "$log_file" | tee -a "$log_file"

# Capture stdout AND stderr, including tracebacks and Python's native-crash dump.
# Use the project's interpreter directly; no activation or working directory needed.
PYTHONUNBUFFERED=1 PYTHONFAULTHANDLER=1 \
    "$project_dir/.venv/bin/python" -m ippon view 2>&1 | tee -a "$log_file"
status=${PIPESTATUS[0]}

printf 'Stopped: %s; exit status: %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$status" | tee -a "$log_file"
exit "$status"
