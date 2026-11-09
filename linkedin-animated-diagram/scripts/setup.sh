#!/usr/bin/env bash
# One-time setup per session: Python renderer, GIF tools, fonts, Lucide icons.
# Safe to run repeatedly; it skips anything already present.
set -u
CACHE="${HOME}/.cache/linkedin-anim"
FONT_DIR="${HOME}/.local/share/fonts/linkedin-anim"
mkdir -p "$CACHE" "$FONT_DIR"

echo "[1/4] Python packages"
python3 -c "import cairosvg" 2>/dev/null || pip install -q cairosvg --break-system-packages
python3 -c "import PIL" 2>/dev/null || pip install -q pillow --break-system-packages
python3 -c "import arabic_reshaper, bidi, fontTools" 2>/dev/null || pip install -q arabic-reshaper python-bidi fonttools --break-system-packages

echo "[2/4] GIF tools"
command -v ffmpeg >/dev/null || { apt-get update -q >/dev/null 2>&1; apt-get install -y -q ffmpeg >/dev/null 2>&1; }
command -v gifsicle >/dev/null || { apt-get install -y -q gifsicle >/dev/null 2>&1 || { apt-get update -q >/dev/null 2>&1; apt-get install -y -q gifsicle >/dev/null 2>&1; }; }
command -v gifsicle >/dev/null || echo "  warning: gifsicle unavailable, GIFs will be larger (ffmpeg only)"

echo "[3/4] Fonts"
BASE="https://raw.githubusercontent.com/google/fonts/main/ofl"
for f in \
  "poppins/Poppins-Regular.ttf" "poppins/Poppins-Bold.ttf" \
  "bebasneue/BebasNeue-Regular.ttf" \
  "dmserifdisplay/DMSerifDisplay-Regular.ttf" \
  "ibmplexmono/IBMPlexMono-Regular.ttf" "ibmplexmono/IBMPlexMono-Bold.ttf" \
  "tajawal/Tajawal-Regular.ttf" "tajawal/Tajawal-Bold.ttf"; do
  name="$(basename "$f")"
  [ -s "$FONT_DIR/$name" ] || curl -sfL "$BASE/$f" -o "$FONT_DIR/$name" || echo "  warning: could not fetch $name (DejaVu Sans fallback)"
done
fc-cache -f "$FONT_DIR" >/dev/null 2>&1

echo "[4/4] Lucide icons"
if [ ! -d "$CACHE/node_modules/lucide-static/icons" ]; then
  (cd "$CACHE" && npm install --silent --no-audit --no-fund lucide-static >/dev/null 2>&1) \
    || echo "  warning: lucide-static install failed, nodes will show step numbers instead of icons"
fi
echo "Setup done. Icons: $(ls "$CACHE/node_modules/lucide-static/icons" 2>/dev/null | wc -l)"
