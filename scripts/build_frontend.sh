#!/usr/bin/env bash
# Build the production frontend and copy it into the Python package so it's
# served by the backend (and bundled into the sdist/wheel). Run this before
# `pip install .` / `python -m build` for a release.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Building frontend..."
cd frontend
npm install
npm run build
cd ..

echo "Copying frontend/dist -> src/local_ai_workspace/static"
rm -rf src/local_ai_workspace/static
cp -r frontend/dist src/local_ai_workspace/static

echo "Done. Static assets: $(du -sh src/local_ai_workspace/static | cut -f1)"
