#!/bin/bash
# Builds the sample-loggers site: this checkout's wheel where the page loads it, and the
# ready-made sets as zips.
#
#   site/build.sh            # then serve site/public, or deploy it with wrangler
#
# The page runs that wheel in the browser with Pyodide, so the site always matches the
# code it is built from. Deploy from a release tag so the page's command line (which pins
# the same version) reproduces its downloads byte for byte.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf site/public/pkg
uv build --wheel --out-dir site/public/pkg -q
mv site/public/pkg/logger_generator-*-py3-none-any.whl site/public/pkg/logger_generator.whl
echo "site/public/pkg/logger_generator.whl ($(uv version --short))"
# The ready-made sets never change within a release, so they are built once here.
rm -rf site/public/sets
uv run -q python -c "import sys; sys.path.insert(0, 'site/public'); import web; web.build_sets('site/public/sets')"
