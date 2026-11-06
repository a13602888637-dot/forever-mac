#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
uv sync --extra dev
exec uv run foreverai serve "$@"
