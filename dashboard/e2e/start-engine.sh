#!/usr/bin/env sh
# Fresh demo database + engine serving the built dashboard. Used by Playwright's webServer.
set -e
cd "$(dirname "$0")/../../engine"
DB="${TMPDIR:-/tmp}/yesrule-e2e-$$.db"
export YESRULE_DATABASE_URL="sqlite:///$DB"
uv run yesrule demo >/dev/null
exec uv run yesrule serve --port "${PORT:-8791}"
