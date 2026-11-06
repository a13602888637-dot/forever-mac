#!/bin/sh
set -eu
cd "$(dirname "$0")"
FAI_UV="$(command -v uv || true)"
if [ -z "$FAI_UV" ]; then
    for FAI_CANDIDATE in "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
        if [ -x "$FAI_CANDIDATE" ]; then FAI_UV="$FAI_CANDIDATE"; break; fi
    done
fi
if [ -z "$FAI_UV" ]; then
    printf '%s\n' '需要先安装 uv：https://docs.astral.sh/uv/getting-started/installation/'
    exit 1
fi
"$FAI_UV" sync --extra dev
exec "$FAI_UV" run python scripts/first_run.py "$@"
