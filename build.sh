#!/usr/bin/env bash
# Package the skill as a ZIP for upload to Claude.ai / Claude Desktop.
# Output: dist/linkedin-animated-diagram.zip
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p dist
python3 - <<'PY'
import os, zipfile
name = "linkedin-animated-diagram"
out = f"dist/{name}.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(name):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".pyc") or f == ".DS_Store":
                continue
            p = os.path.join(root, f)
            z.write(p, p)
print(f"built {out} ({os.path.getsize(out) // 1024} KB)")
PY
