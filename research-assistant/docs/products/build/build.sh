#!/usr/bin/env bash
# Rebuild both per-product reports, HTML and .docx, from the content modules.
#
# Run from docs/products/. The docx generator is copied up to docs/ first
# because require("docx") resolves relative to the script and the package is
# reachable from docs/ but not from docs/products/build/.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 build/render_html.py

cp build/render-docx.js ../_p.js
trap 'rm -f ../_p.js' EXIT
node ../_p.js build/deep-research.json   build/figures Cognita-Deep-Research-Report.docx
node ../_p.js build/chat-with-files.json build/figures Cognita-Chat-with-Files-Report.docx
rm -f ../_p.js; trap - EXIT

python3 ../build/fix-bookmarks.py Cognita-Deep-Research-Report.docx
python3 ../build/fix-bookmarks.py Cognita-Chat-with-Files-Report.docx
