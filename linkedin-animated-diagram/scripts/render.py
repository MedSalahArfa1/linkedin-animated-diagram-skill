#!/usr/bin/env python3
"""Render an animated flow-diagram GIF (flowing dotted connectors) from a JSON spec.

  python render.py spec.json --preview preview.png      # still frame to inspect
  python render.py spec.json --gif out.gif               # final looping GIF
  python render.py --icons brain database cloud          # search Lucide icon names
  python render.py --palettes | --styles                 # list presets
  python render.py --swatches out.png --mode dark --swatch-names blues greens "#112233,#445566"

See ../references/spec.md for the spec format.
"""
import argparse, base64, io, json, math, os, random, re, shutil, subprocess, sys, tempfile, unicodedata
from concurrent.futures import ProcessPoolExecutor
from xml.sax.saxutils import escape

HOME = os.path.expanduser("~")
LUCIDE = os.path.join(HOME, ".cache/linkedin-anim/node_modules/lucide-static")
FONT_DIR = os.path.join(HOME, ".local/share/fonts/linkedin-anim")
WARN = []

def warn(msg):
    WARN.append(msg)

# =============================================================== fonts & text
FONTS = {  # family -> (regular file, bold file)
    "Poppins": ("Poppins-Regular.ttf", "Poppins-Bold.ttf"),
    "Bebas Neue": ("BebasNeue-Regular.ttf", "BebasNeue-Regular.ttf"),
    "DM Serif Display": ("DMSerifDisplay-Regular.ttf", "DMSerifDisplay-Regular.ttf"),
    "IBM Plex Mono": ("IBMPlexMono-Regular.ttf", "IBMPlexMono-Bold.ttf"),
    "Tajawal": ("Tajawal-Regular.ttf", "Tajawal-Bold.ttf"),
}
FALLBACK = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
RTL_LANGS = {"ar", "fa", "ur"}
_font_cache, _cmap = {}, {}

def has_bold(family):
    f = FONTS.get(family)
    return not f or f[0] != f[1]

def family_for(text, family):
    return "Tajawal" if ARABIC.search(text or "") else family

def font_path(family, bold):
    files = FONTS.get(family)
    if files:
        p = os.path.join(FONT_DIR, files[1 if bold and has_bold(family) else 0])
        if os.path.exists(p):
            return p, family
    warn(f"font '{family}' missing (run setup.sh), using DejaVu Sans")
    return FALLBACK[1 if bold else 0], "DejaVu Sans"

def shape(text):
    """Arabic: join letters (presentation forms) and reorder for display."""
    if not ARABIC.search(text or ""):
        return text
    import arabic_reshaper
    from bidi.algorithm import get_display
    out = get_display(arabic_reshaper.reshape(text))
    if "Tajawal" not in _cmap:
        from fontTools.ttLib import TTFont
        _cmap["Tajawal"] = TTFont(font_path("Tajawal", True)[0]).getBestCmap()
    cm, fixed = _cmap["Tajawal"], []
    for ch in out:
        if ch == " " or ord(ch) in cm:
            fixed.append(ch)
        else:  # font lacks this presentation form: fall back to the base letter
            d = unicodedata.decomposition(ch).split()
            fixed.append(chr(int(d[-1], 16)) if d and d[-1] != "<isolated>" else ch)
    return "".join(fixed)

def text_width(text, family, size, bold):
    from PIL import ImageFont
    fam = family_for(text, family)
    bold = bold and has_bold(fam)
    key = (fam, bold, int(size))
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(font_path(fam, bold)[0], int(size))
    return _font_cache[key].getlength(shape(text))

def txt(x, y, text, size, family, fill, bold=True, anchor="start", extra=""):
    fam = family_for(text, family)
    real = font_path(fam, bold)[1]
    w = 'font-weight="bold"' if bold and has_bold(fam) else ""
    a = "" if anchor == "start" else f'text-anchor="{anchor}"'
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:.1f}" font-family="{real}" {w} {a} '
            f'fill="{fill}" {extra}>{escape(shape(text))}</text>')

def wrap(text, family, size, bold, maxw, max_lines=2, min_size=15):
    """Greedy word wrap on logical text; shrinks the font until it fits in max_lines."""
    s = size
    while True:
        lines, cur = [], ""
        for w in text.split():
            t = (cur + " " + w).strip()
            if text_width(t, family, s, bold) <= maxw or not cur:
                cur = t
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        fits = len(lines) <= max_lines and all(text_width(l, family, s, bold) <= maxw for l in lines)
        if fits or s <= min_size:
            if not fits:
                warn(f"text too long, truncated: '{text}'")
                lines = lines[:max_lines]
                while lines[-1] and text_width(lines[-1] + "…", family, s, bold) > maxw:
                    lines[-1] = lines[-1][:-1]
                lines[-1] += "…"
            return lines, s
        s -= 1

# =============================================================== colors
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

def norm_hex(c):
    c = str(c).strip()
    if not c.startswith("#"):
        c = "#" + c
    if re.fullmatch(r"#[0-9A-Fa-f]{3}", c):
        c = "#" + "".join(ch * 2 for ch in c[1:])
    if not HEX.match(c):
        sys.exit(f"spec error: '{c}' is not a hex color like #1A2B3C")
    return c.upper()

def mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))

def lum(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)

def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)

# Palettes are named by color. Each has a light-mode variant (deeper shades, readable on white)
# and a dark-mode variant (brighter shades, readable on near-black).
PALETTES = {
    "blues":        ("Blues",          ["#1D4ED8", "#0369A1", "#2563EB", "#1E40AF"], ["#60A5FA", "#38BDF8", "#93C5FD", "#3B82F6"]),
    "teal-cyan":    ("Teal & Cyan",    ["#0F766E", "#0E7490", "#0D9488", "#155E75"], ["#2DD4BF", "#22D3EE", "#5EEAD4", "#67E8F9"]),
    "blue-teal":    ("Blue & Teal",    ["#0369A1", "#0D9488", "#4F46E5", "#0284C7"], ["#38BDF8", "#2DD4BF", "#818CF8", "#7DD3FC"]),
    "greens":       ("Greens",         ["#15803D", "#047857", "#4D7C0F", "#166534"], ["#4ADE80", "#34D399", "#A3E635", "#86EFAC"]),
    "green-brown":  ("Green & Brown",  ["#15803D", "#92400E", "#4D7C0F", "#A16207"], ["#4ADE80", "#FBBF24", "#A3E635", "#FDBA74"]),
    "reds-oranges": ("Reds & Oranges", ["#DC2626", "#EA580C", "#B91C1C", "#C2410C"], ["#F87171", "#FB923C", "#FCA5A5", "#FDBA74"]),
    "amber-gold":   ("Amber & Gold",   ["#B45309", "#A16207", "#C2410C", "#92400E"], ["#FBBF24", "#FACC15", "#FB923C", "#FCD34D"]),
    "purples":      ("Purples",        ["#7C3AED", "#9333EA", "#6D28D9", "#A21CAF"], ["#A78BFA", "#C084FC", "#E879F9", "#8B5CF6"]),
    "pink-purple":  ("Pink & Purple",  ["#DB2777", "#7C3AED", "#BE185D", "#9333EA"], ["#F472B6", "#A78BFA", "#F9A8D4", "#C084FC"]),
    "blue-orange":  ("Blue & Orange",  ["#1D4ED8", "#EA580C", "#0369A1", "#C2410C"], ["#60A5FA", "#FB923C", "#38BDF8", "#FDBA74"]),
    "red-purple":   ("Red & Purple",   ["#E11D48", "#7C3AED", "#BE123C", "#6D28D9"], ["#FB7185", "#A78BFA", "#FDA4AF", "#C4B5FD"]),
    "multicolor":   ("Multicolor",     ["#E11D48", "#7C3AED", "#0284C7", "#D97706"], ["#FB7185", "#A78BFA", "#38BDF8", "#FBBF24"]),
    "grayscale":    ("Grayscale",      ["#111827", "#374151", "#4B5563", "#1F2937"], ["#F3F4F6", "#D1D5DB", "#E5E7EB", "#9CA3AF"]),
    # premium: restrained, high-contrast pairings that look at home in the LinkedIn feed
    "linkedin-blue":    ("LinkedIn Blue",           ["#0A66C2", "#004182", "#378FE9", "#0F4C81"], ["#70B5F9", "#378FE9", "#A8D4FF", "#4DA3F7"]),
    "navy-gold":        ("Navy & Gold",             ["#1E3A8A", "#A16207", "#1E40AF", "#854D0E"], ["#93C5FD", "#FACC15", "#60A5FA", "#FDE68A"]),
    "indigo-coral":     ("Indigo & Coral",          ["#4338CA", "#CC3D10", "#3730A3", "#B4380C"], ["#A5B4FC", "#FF8A65", "#818CF8", "#FDBA74"]),
    "emerald-slate":    ("Emerald & Slate",         ["#047857", "#334155", "#059669", "#1E293B"], ["#34D399", "#CBD5E1", "#6EE7B7", "#94A3B8"]),
    "burgundy-gold":    ("Burgundy & Gold",         ["#9F1239", "#A16207", "#881337", "#854D0E"], ["#FDA4AF", "#FCD34D", "#FB7185", "#FBBF24"]),
    "teal-coral":       ("Teal & Coral",            ["#0F766E", "#CC3D10", "#115E59", "#B4380C"], ["#5EEAD4", "#FF8A65", "#2DD4BF", "#FDBA74"]),
    "plum-rose":        ("Plum & Rose",             ["#6B21A8", "#BE185D", "#581C87", "#9D174D"], ["#D8B4FE", "#F9A8D4", "#C084FC", "#F472B6"]),
    "charcoal-electric":("Charcoal & Electric Blue",["#1F2937", "#2563EB", "#374151", "#1D4ED8"], ["#E5E7EB", "#60A5FA", "#D1D5DB", "#93C5FD"]),
}
PREMIUM = {"linkedin-blue", "navy-gold", "indigo-coral", "emerald-slate", "burgundy-gold", "teal-coral",
           "plum-rose", "charcoal-electric"}
MODES = {
    "light": dict(bg="#FFFFFF", text="#111827", muted="#6B7280"),
    "dark":  dict(bg="#0A0F1C", text="#F1F5F9", muted="#94A3B8"),
}
STYLES = {
    "clean":     dict(title_font="Poppins", body_font="Poppins", node_style="filled", node_shape="circle", label_color="section",
                      desc="Filled circles, colored labels. Safe default for AI/ML and general explainers."),
    "tech":      dict(title_font="Poppins", body_font="Poppins", node_style="glow", node_shape="rounded", label_color="text",
                      desc="Rounded squares with tinted fill and colored outline. Infra, cloud, GPUs, security, IoT."),
    "code":      dict(title_font="IBM Plex Mono", body_font="IBM Plex Mono", node_style="outline", node_shape="rounded", label_color="text",
                      desc="Monospace, outlined rounded nodes. DevOps, CI/CD, backend, APIs, CLI."),
    "editorial": dict(title_font="DM Serif Display", body_font="Poppins", node_style="outline", node_shape="circle", label_color="text",
                      desc="Serif title, outlined circles. Business, strategy, careers, research."),
    "bold":      dict(title_font="Bebas Neue", body_font="Poppins", node_style="filled", node_shape="circle", label_color="text",
                      desc="Tall condensed title, filled circles. Hot takes, myths vs facts, bold opinions."),
    "soft":      dict(title_font="Poppins", body_font="Poppins", node_style="soft", node_shape="circle", label_color="section",
                      desc="Tinted circles, gentle look. Learning, productivity, wellbeing, nature."),
}
CTA_TEXT = {  # order: Like, Comment, Repost, Follow
    "en": ["Like", "Comment", "Repost", "Follow"],
    "fr": ["J'aime", "Commenter", "Republier", "Suivre"],
    "ar": ["أعجبني", "علّق", "أعد النشر", "تابعني"],
    "es": ["Me gusta", "Comentar", "Compartir", "Seguir"],
    "de": ["Gefällt mir", "Kommentieren", "Teilen", "Folgen"],
    "it": ["Mi piace", "Commenta", "Condividi", "Segui"],
    "pt": ["Gostei", "Comentar", "Compartilhar", "Seguir"],
    "nl": ["Vind ik leuk", "Reageren", "Delen", "Volgen"],
    "tr": ["Beğen", "Yorum yap", "Paylaş", "Takip et"],
}
CTA_ICONS = ["thumbs-up", "message-circle", "repeat-2", "user-plus"]

def resolve_theme(spec):
    mode = spec.get("mode", "light")
    if mode not in MODES:
        sys.exit("spec error: mode must be 'light' or 'dark'")
    style = spec.get("style", "clean")
    if style not in STYLES:
        warn(f"unknown style '{style}', using clean"); style = "clean"
    th = dict(STYLES[style]); th["mode"] = mode
    pal = spec.get("palette", "blue-teal")
    custom = {}
    if isinstance(pal, str):
        if pal not in PALETTES:
            sys.exit(f"spec error: unknown palette '{pal}' (see --palettes) or give a list of hex colors")
        cols = PALETTES[pal][1 if mode == "light" else 2]
    elif isinstance(pal, list):
        cols = [norm_hex(c) for c in pal]
    else:  # {"colors": [...], "bg": .., "text": ..}
        cols = [norm_hex(c) for c in pal["colors"]]
        custom = {k: norm_hex(pal[k]) for k in ("bg", "text", "muted") if pal.get(k)}
    if not cols:
        sys.exit("spec error: palette needs at least one color")
    th["colors"] = cols
    base = MODES[mode]
    # a faint tint of the palette in the background ties the canvas to the colors
    th["bg"] = mix(base["bg"], cols[0], 0.025 if mode == "light" else 0.06)
    th["text"], th["muted"] = base["text"], base["muted"]
    th.update(custom)
    th.update({k: v for k, v in spec.get("overrides", {}).items()})
    for k in ("bg", "text", "muted"):
        th[k] = norm_hex(th[k])
    if contrast(th["text"], th["bg"]) < 4.5:
        warn(f"text {th['text']} has low contrast on background {th['bg']}")
    for c in cols:
        if contrast(c, th["bg"]) < 2.2:
            warn(f"color {c} is hard to see on the {mode} background; "
                 f"use a {'darker' if mode == 'light' else 'lighter'} shade or switch mode")
    return th

# =============================================================== icons
_icon_cache = {}

def icon_inner(name, quiet=False):
    if name in _icon_cache:
        return _icon_cache[name]
    p = os.path.join(LUCIDE, "icons", f"{name}.svg")
    inner = None
    if name and os.path.exists(p):
        m = re.search(r"<svg[^>]*>(.*)</svg>", open(p).read(), re.S)
        inner = m.group(1) if m else None
    elif name and not quiet:
        warn(f"icon '{name}' not found (run --icons to search)")
    _icon_cache[name] = inner
    return inner

def icon_svg(name, cx, cy, size, color, sw=2, extra=""):
    inner = icon_inner(name)
    if not inner:
        return ""
    s = size / 24
    return (f'<g transform="translate({cx - 12 * s:.2f},{cy - 12 * s:.2f}) scale({s:.4f})" fill="none" '
            f'stroke="{color}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round" {extra}>'
            f'{inner.replace("currentColor", color)}</g>')

def search_icons(words):
    tp = os.path.join(LUCIDE, "tags.json")
    tags = json.load(open(tp)) if os.path.exists(tp) else {}
    names = sorted(f[:-4] for f in os.listdir(os.path.join(LUCIDE, "icons")) if f.endswith(".svg"))
    for w in words:
        w = w.lower()
        hits = [n for n in names if w in n]
        hits += [n for n in names if n not in hits and any(w in t.lower() for t in tags.get(n, []))]
        print(f"{w}: {', '.join(hits[:30]) or '(none)'}")

# =============================================================== avatar
def avatar_data(path):
    """Square-crop (biased to the top, where faces are), resize, return PNG data URI."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    w, h = im.size
    s = min(w, h)
    left = (w - s) // 2
    top = int((h - s) * 0.3)
    im = im.crop((left, top, left + s, top + s)).resize((256, 256), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

# =============================================================== background
def edge_factor(x, y, W, H):
    d = max(abs(x - W / 2) / (W / 2), abs(y - H / 2) / (H / 2))
    return min(1.0, max(0.0, (d - 0.25) / 0.6))

def background_svg(L, spec):
    """Large, very faint subject icons scattered near the edges. Static, so the GIF stays small."""
    th, W, H, cols = L["th"], L["W"], L["H"], L["th"]["colors"]
    bgs = spec.get("background", {}) or {}
    dark = th["mode"] == "dark"
    out, placed = [], []
    # soft blurred light circles in two opposite corners (top-left, bottom-right)
    if bgs.get("glows", True):
        for i, (x, y) in enumerate([(W * 0.02, H * 0.03), (W * 0.98, H * 0.97)]):
            c = cols[i % len(cols)]
            r = W * 0.62
            out.append(f'<radialGradient id="glow{i}" cx="{x:.0f}" cy="{y:.0f}" r="{r:.0f}" gradientUnits="userSpaceOnUse">'
                       f'<stop offset="0" stop-color="{c}" stop-opacity="{0.22 if dark else 0.16}"/>'
                       f'<stop offset="0.45" stop-color="{c}" stop-opacity="{0.09 if dark else 0.06}"/>'
                       f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>'
                       f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.0f}" fill="url(#glow{i})"/>')
    icons = [n for n in bgs.get("icons", []) if icon_inner(n)]
    if not icons:
        return "".join(out)
    rnd = random.Random(bgs.get("seed", sum(map(ord, json.dumps(spec.get("title", ""))))))
    opacity = (0.055 if dark else 0.038) * float(bgs.get("intensity", 1.0))
    for i in range(min(12, 4 + 3 * len(icons))):
        for _ in range(300):
            x, y = rnd.uniform(40, W - 40), rnd.uniform(40, H - 40)
            if edge_factor(x, y, W, H) > 0.6 and all((x - a) ** 2 + (y - b) ** 2 > 170 ** 2 for a, b in placed):
                placed.append((x, y))
                g = icon_svg(icons[i % len(icons)], x, y, rnd.uniform(70, 130), cols[i % len(cols)], 1.6,
                             f'opacity="{opacity:.3f}"')
                out.append(g.replace('<g transform="', f'<g transform="rotate({rnd.uniform(-25, 25):.0f} {x:.0f} {y:.0f}) ', 1))
                break
    return "".join(out)

# =============================================================== layout
CANVAS = {"4:5": (1080, 1350), "1:1": (1080, 1080), "16:9": (1920, 1080)}

def color_ref(c, th, colors):
    if c is None:
        return th["text"]
    if isinstance(c, str) and re.fullmatch(r"s\d", c):
        return colors[int(c[1]) % len(colors)]
    return {"text": th["text"], "muted": th["muted"]}.get(c, c)

def short_link(url):
    u = re.sub(r"^https?://", "", (url or "").strip()).rstrip("/")
    return re.sub(r"^(www\.|[a-z]{2}\.)linkedin", "linkedin", u)

def layout(spec):
    th = resolve_theme(spec)
    lang = spec.get("lang", "en")
    rtl = lang in RTL_LANGS
    if rtl:
        th["title_font"] = th["body_font"] = "Tajawal"
    W, H = CANVAS.get(spec.get("canvas", "4:5"), CANVAS["4:5"])
    M = 56
    tf, bf = th["title_font"], th["body_font"]
    sections = spec["sections"]
    if not 1 <= len(sections) <= 3:
        sys.exit("spec error: 1 to 3 sections supported")
    colors = [s.get("color") or th["colors"][i % len(th["colors"])] for i, s in enumerate(sections)]
    colors = [norm_hex(c) for c in colors]
    ref_colors = colors + [c for c in th["colors"] if c not in colors]
    L = dict(W=W, H=H, th=th, colors=colors, sections=[], rtl=rtl, lang=lang, M=M, ref=ref_colors)
    y = 40

    # ---- author badge

    # ---- title (string or list of {text,color}); segments listed in reading order
    segs = spec.get("title", "")
    if isinstance(segs, str):
        segs = [{"text": segs, "color": "text"}]
    max_size = 150 if tf == "Bebas Neue" else 104
    gap = lambda s: max(text_width(" ", tf, s, True), s * 0.28)
    def seg_w(sg, s):
        t = sg["text"]
        return text_width(t.strip(), tf, s, True) + (len(t) - len(t.strip())) * gap(s)
    size = max_size
    full = sum(seg_w(sg, size) for sg in segs)
    if full > W - 2 * M:
        size = max(40, size * (W - 2 * M) / full)
    widths = [seg_w(sg, size) for sg in segs]
    total = sum(widths)
    placed = []
    x = (W - total) / 2 if not rtl else (W + total) / 2
    for sg, w0 in zip(segs, widths):
        t = sg["text"]
        nlead = len(t) - len(t.lstrip()); ntrail = len(t) - len(t.rstrip())
        core = text_width(t.strip(), tf, size, True)
        if rtl:
            right = x - (nlead * gap(size))
            placed.append((t.strip(), color_ref(sg.get("color"), th, ref_colors), right - core))
            x -= w0
        else:
            placed.append((t.strip(), color_ref(sg.get("color"), th, ref_colors), x + nlead * gap(size)))
            x += w0
    L["title"] = dict(segs=placed, size=size, y=y + size * 0.82)
    y += size * 1.02

    if spec.get("subtitle"):
        lines, ss = wrap(spec["subtitle"], bf, 26, False, W - 2 * M - 40, 2, 18)
        L["subtitle"] = dict(lines=lines, size=ss, y=y + ss + 8)
        y += len(lines) * ss * 1.35 + 10
    y += 14

    # ---- bottom: optional footer line + CTA pills
    cta = spec.get("cta", True)
    if cta is True:
        cta = CTA_TEXT.get(lang)
        if not cta:
            warn(f"no built-in CTA for '{lang}'; pass \"cta\": [three translated words]. Using English.")
            cta = CTA_TEXT["en"]
    bottom = H - 22
    if cta:
        if len(cta) != 4:
            sys.exit("spec error: cta needs 4 words in this order: Like, Comment, Repost, Follow")
        ph, fs, gapx = 52, 21, 14
        while True:  # shrink the text if four pills don't fit the width
            pills = [dict(text=t, icon=CTA_ICONS[i], w=24 + 26 + 9 + text_width(t, bf, fs, True))
                     for i, t in enumerate(cta)]
            if sum(p["w"] for p in pills) + gapx * 3 <= W - 2 * M or fs <= 15:
                break
            fs -= 1
        tw = sum(p["w"] for p in pills) + gapx * (len(pills) - 1)
        x = (W - tw) / 2
        order = pills[::-1] if rtl else pills
        for p in order:
            p["x"] = x; x += p["w"] + gapx
        L["cta"] = dict(pills=pills, y=bottom - ph, h=ph, fs=fs)
        bottom -= ph + 18
    a = spec.get("author")
    if a and a.get("name"):
        # author card: rounded rectangle with an animated dashed border, sitting above the CTA
        avatar = a.get("avatar")
        if avatar and not os.path.exists(avatar):
            warn(f"avatar '{avatar}' not found, showing name only"); avatar = None
        ar = 30 if avatar else 0
        link = short_link(a.get("linkedin", ""))
        subs = []
        if link:
            subs.append(("link", link, 19))
        if a.get("tagline"):
            subs.append(("tag", a["tagline"], 17))
        widths = [text_width(a["name"], bf, 26, True)]
        widths += [text_width(t, "Poppins", z, False) + 30 if k == "link" else text_width(t, bf, z, False)
                   for k, t, z in subs]
        tw = max(widths)
        block_h = 28 + sum(z * 1.3 for _, _, z in subs)
        padx, pady = 30, 14
        content_w = tw + (2 * ar + 18 if avatar else 0)
        bw = content_w + 2 * padx
        bh = max(block_h, 2 * ar) + 2 * pady
        bx, by = (W - bw) / 2, bottom - bh
        cy = by + bh / 2
        if avatar:
            if rtl:
                cx, tx, anchor = bx + bw - padx - ar, bx + bw - padx - 2 * ar - 18, "end"
            else:
                cx, tx, anchor = bx + padx + ar, bx + padx + 2 * ar + 18, "start"
        else:
            cx, tx, anchor = None, W / 2, "middle"
        L["author"] = dict(box=(bx, by, bw, bh), cx=cx, cy=cy, r=ar, tx=tx, anchor=anchor,
                           ty=cy - block_h / 2 + 22, subs=subs, a=a,
                           avatar=avatar_data(avatar) if avatar else None)
        bottom -= bh + 18
    if spec.get("footer"):
        L["footer"] = dict(text=spec["footer"], y=bottom - 6)
        bottom -= 40
    body_top, body_bot = y, bottom

    # ---- sections and rows
    head_h, sgap = 66, 12
    plans = []
    for s in sections:
        slots = [st if isinstance(st, list) else [st] for st in s["steps"]]
        if len(slots) > 12:
            sys.exit("spec error: max 12 steps per section")
        if any(len(sl) > 2 for sl in slots):
            sys.exit("spec error: a parallel group holds at most 2 steps")
        n = len(slots)
        maxc = s.get("columns") or (5 if W > 1500 else 4)
        rows = math.ceil(n / maxc)
        cols = math.ceil(n / rows)
        weights = [1.62 if any(len(sl) == 2 for sl in slots[r * cols:(r + 1) * cols]) else 1.0 for r in range(rows)]
        plans.append((s, slots, rows, cols, weights))
    total_w = sum(sum(p[4]) for p in plans)
    avail = body_bot - body_top - len(plans) * (head_h + sgap)
    row_h = min(avail / total_w, 300)
    used = total_w * row_h + len(plans) * (head_h + sgap)
    y = body_top + max(0, (body_bot - body_top - used) / 2)

    turn = 46
    inner_w = W - 2 * M - 2 * turn
    for si, (s, slots, rows, cols, weights) in enumerate(plans):
        col = colors[si]
        sec = dict(color=col, heading=s.get("heading", ""), y=y, nodes=[], edges=[], hsize=40)
        if sec["heading"]:
            hl, hs = wrap(sec["heading"], bf, 40, True, W - 2 * M, 1, 22)
            sec["heading"], sec["hsize"] = hl[0], hs
        y += head_h
        cell_w = inner_w / cols
        has_par = any(len(sl) == 2 for sl in slots)
        r = min(cell_w * 0.25, row_h * 0.25, 64)
        lab_size = max(17, min(28, r * 0.46))
        if has_par and row_h < 170:
            warn("rows are short for parallel steps; consider fewer steps or 1 parallel group")
        row_top = [y + row_h * sum(weights[:k]) for k in range(rows)]
        slot_pts = []
        for i, sl in enumerate(slots):
            row, k = divmod(i, cols)
            ltr = (row % 2 == 0) != rtl  # snake; RTL languages start on the right
            c = k if ltr else (cols - 1 - k)
            cx = M + turn + cell_w * (c + 0.5)
            rh = row_h * weights[row]
            cy = row_top[row] + rh * (0.53 if weights[row] > 1 else 0.40)
            pts = []
            if len(sl) == 1:
                pts.append(dict(cx=cx, cy=cy, r=r, step=sl[0], label_pos="below"))
            else:
                pr, d = r * 0.82, rh * 0.25
                pts.append(dict(cx=cx, cy=cy - d, r=pr, step=sl[0], label_pos="above"))
                pts.append(dict(cx=cx, cy=cy + d, r=pr, step=sl[1], label_pos="below"))
            for p in pts:
                p.update(slot=i, row=row, dir=1 if ltr else -1,
                         color=norm_hex(color_ref(p["step"]["color"], th, ref_colors)) if p["step"].get("color") else col)
                p["lines"], p["lsize"] = wrap(p["step"].get("label", ""), bf, lab_size, True, cell_w * 0.94, 2, 15)
                sec["nodes"].append(p)
            slot_pts.append(pts)
        sec["nslots"] = len(slots)
        for i in range(len(slots) - 1):
            A, B = slot_pts[i], slot_pts[i + 1]
            pairs = list(zip(A, B)) if len(A) == len(B) == 2 else [(a_, b_) for a_ in A for b_ in B]
            for a_, b_ in pairs:
                sec["edges"].append(edge_path(a_, b_, turn * 1.7))
        y += row_h * sum(weights) + sgap
        L["sections"].append(sec)
    return L

def edge_path(a, b, bulge):
    ga, gb = a["r"] + 10, b["r"] + 10
    d = a["dir"]
    if a["row"] == b["row"]:
        sx, sy = a["cx"] + d * ga, a["cy"]
        ex, ey = b["cx"] - d * gb, b["cy"]
        mx = (ex - sx) * 0.5
        return f"M{sx:.1f},{sy:.1f} C{sx + mx:.1f},{sy:.1f} {ex - mx:.1f},{ey:.1f} {ex:.1f},{ey:.1f}"
    sx, sy = a["cx"] + d * ga, a["cy"]
    ex, ey = b["cx"] + d * gb, b["cy"]
    bx = max(sx, ex) + bulge if d > 0 else min(sx, ex) - bulge
    return f"M{sx:.1f},{sy:.1f} C{bx:.1f},{sy:.1f} {bx:.1f},{ey:.1f} {ex:.1f},{ey:.1f}"

# =============================================================== svg
def node_svg(p, idx, col, th):
    st, r, cx, cy, bg = th["node_style"], p["r"], p["cx"], p["cy"], th["bg"]
    if st == "filled":
        fill, stroke, sw = col, "none", 0
        ic = "#FFFFFF" if contrast(col, "#FFFFFF") >= 2.6 else mix(bg, "#000000", 0.3)
    elif st == "outline":
        fill, stroke, sw, ic = bg, col, 4, col
    elif st == "soft":
        fill, stroke, sw, ic = mix(col, bg, 0.82), "none", 0, col
    else:  # glow
        fill, stroke, sw, ic = mix(col, bg, 0.80), col, 3, col
    if th["node_shape"] == "rounded":
        body = (f'<rect x="{cx - r:.1f}" y="{cy - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" '
                f'rx="{r * 0.34:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    else:
        body = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
    ico = icon_svg(p["step"].get("icon"), cx, cy, r, ic)
    if ico:
        return body + ico
    fs = r * 0.8
    return body + txt(cx, cy + fs * 0.35, str(idx + 1), fs, th["body_font"], ic, anchor="middle")

def label_svg(p, col, th):
    lc = col if th["label_color"] == "section" else th["text"]
    ls, lines = p["lsize"], p["lines"]
    lh = ls * 1.18
    if p["label_pos"] == "below":
        y0 = p["cy"] + p["r"] + 12 + ls * 0.85
    else:
        y0 = p["cy"] - p["r"] - 12 - (len(lines) - 1) * lh - ls * 0.2
    return "".join(txt(p["cx"], y0 + i * lh, l, ls, th["body_font"], lc, anchor="middle") for i, l in enumerate(lines))

def static_svg(L, spec):
    th, W, H, M, rtl = L["th"], L["W"], L["H"], L["M"], L["rtl"]
    bf, tf = th["body_font"], th["title_font"]
    out = [f'<rect width="{W}" height="{H}" fill="{th["bg"]}"/>', background_svg(L, spec)]
    acc = L["colors"][0]
    if "author" in L:
        A = L["author"]; a = A["a"]
        bx, by, bw, bh = A["box"]
        out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="18" '
                   f'fill="{mix(acc, th["bg"], 0.93)}"/>')
        if A["avatar"]:  # photo only; without one, no circle is drawn at all
            out.append(f'<clipPath id="avc"><circle cx="{A["cx"]:.1f}" cy="{A["cy"]:.1f}" r="{A["r"]}"/></clipPath>'
                       f'<image href="{A["avatar"]}" x="{A["cx"] - A["r"]:.1f}" y="{A["cy"] - A["r"]:.1f}" '
                       f'width="{2 * A["r"]}" height="{2 * A["r"]}" clip-path="url(#avc)"/>'
                       f'<circle cx="{A["cx"]:.1f}" cy="{A["cy"]:.1f}" r="{A["r"] + 3.5}" fill="none" stroke="{acc}" stroke-width="3"/>')
        anchor = A["anchor"]
        ty = A["ty"]
        out.append(txt(A["tx"], ty, a["name"], 26, bf, th["text"], anchor=anchor))
        ty += 6
        for kind, t, z in A["subs"]:
            ty += z * 1.3
            if kind == "link":
                bs = z + 3
                tw = text_width(t, "Poppins", z, False)
                if anchor == "middle":   # [in] url, centered as one group
                    bx = A["tx"] - (bs + 8 + tw) / 2
                    ux = bx + bs + 8
                elif anchor == "end":    # RTL: url [in], ending at the text edge
                    bx = A["tx"] - bs
                    ux = bx - 11 - tw
                else:
                    bx = A["tx"]
                    ux = bx + bs + 8
                out.append(f'<rect x="{bx:.1f}" y="{ty - bs + 3:.1f}" width="{bs}" height="{bs}" rx="4" fill="#0A66C2"/>'
                           + txt(bx + bs / 2, ty - 1, "in", z * 0.82, "Poppins", "#FFFFFF", anchor="middle"))
                out.append(txt(ux, ty, t, z, "Poppins", th["muted"], bold=False))  # URLs read left-to-right
            else:
                out.append(txt(A["tx"], ty, t, z, bf, th["muted"], bold=False, anchor=anchor))
    T = L["title"]
    for t, c, x in T["segs"]:
        if t:
            out.append(txt(x, T["y"], t, T["size"], tf, c))
    if "subtitle" in L:
        S = L["subtitle"]
        for i, l in enumerate(S["lines"]):
            out.append(txt(W / 2, S["y"] + i * S["size"] * 1.35, l, S["size"], bf, th["muted"], bold=False, anchor="middle"))
    for sec in L["sections"]:
        col = sec["color"]
        out.append(f'<line x1="{M}" y1="{sec["y"] + 6:.1f}" x2="{W - M}" y2="{sec["y"] + 6:.1f}" stroke="{col}" '
                   f'stroke-width="2" stroke-dasharray="8 7" opacity="0.7"/>')
        if sec["heading"]:
            out.append(txt(W / 2, sec["y"] + 16 + sec["hsize"], sec["heading"], sec["hsize"], bf, col, anchor="middle"))
    if "footer" in L:
        F = L["footer"]
        out.append(txt(W / 2, F["y"], F["text"], 22, bf, th["muted"], bold=False, anchor="middle"))
    if "cta" in L:
        C = L["cta"]
        for p in C["pills"]:
            x, y, h = p["x"], C["y"], C["h"]
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{p["w"]:.1f}" height="{h}" rx="{h / 2}" '
                       f'fill="{mix(acc, th["bg"], 0.88)}" stroke="{acc}" stroke-width="2"/>')
            if rtl:
                icx, tx_, anc = x + p["w"] - 12 - 13, x + p["w"] - 12 - 26 - 9, "end"
            else:
                icx, tx_, anc = x + 12 + 13, x + 12 + 26 + 9, "start"
            out.append(icon_svg(p["icon"], icx, y + h / 2, 24, acc, 2.2))
            out.append(txt(tx_, y + h / 2 + C["fs"] * 0.36, p["text"], C["fs"], bf, th["text"], anchor=anc))
    return "".join(out)

def nodes_svg(L):
    out = []
    for sec in L["sections"]:
        for p in sec["nodes"]:
            out.append(node_svg(p, p["slot"], p["color"], L["th"]))
            out.append(label_svg(p, p["color"], L["th"]))
    return "".join(out)

def dyn_svg(L, phase, cycles):
    """Everything that moves: connectors (dash offset), node ripples, author card border."""
    out = []
    th = L["th"]
    if "author" in L:
        bx, by, bw, bh = L["author"]["box"]
        rx = 18
        perim = 2 * (bw + bh) - (8 - 2 * math.pi) * rx
        period = perim / max(1, round(perim / 22))  # whole number of dashes: no seam on the border
        out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="{rx}" fill="none" '
                   f'stroke="{L["colors"][0]}" stroke-width="3" stroke-linecap="round" '
                   f'stroke-dasharray="{period * 0.55:.2f} {period * 0.45:.2f}" '
                   f'stroke-dashoffset="{-phase * max(1, round(cycles * 0.6)) * period:.2f}"/>')
    for sec in L["sections"]:
        col = sec["color"]
        rmin = min(p["r"] for p in sec["nodes"])
        sw = max(5.0, rmin * 0.12)
        period = sw * 2.8
        off = -phase * cycles * period
        for d in sec["edges"]:
            out.append(f'<path d="{d}" fill="none" stroke="{mix(col, th["bg"], 0.8)}" stroke-width="{sw * 0.45:.1f}"/>')
            out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{sw:.1f}" stroke-linecap="round" '
                       f'stroke-dasharray="0.01 {period:.2f}" stroke-dashoffset="{off:.2f}"/>')
        N = sec["nslots"]
        for p in sec["nodes"]:
            u = ((phase - p["slot"] / N) % 1.0) * N / 1.6
            if u < 1:
                rr = p["r"] + 6 + 20 * u
                attrs = f'fill="none" stroke="{p["color"]}" stroke-width="{4 * (1 - u) + 1:.1f}" opacity="{0.6 * (1 - u):.2f}"'
                if th["node_shape"] == "rounded":
                    out.append(f'<rect x="{p["cx"] - rr:.1f}" y="{p["cy"] - rr:.1f}" width="{2 * rr:.1f}" '
                               f'height="{2 * rr:.1f}" rx="{rr * 0.34:.1f}" {attrs}/>')
                else:
                    out.append(f'<circle cx="{p["cx"]:.1f}" cy="{p["cy"]:.1f}" r="{rr:.1f}" {attrs}/>')
    return "".join(out)

def frame_svg(L, static, nodes, phase, cycles):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{L["W"]}" height="{L["H"]}" viewBox="0 0 {L["W"]} {L["H"]}">'
            f'{static}{dyn_svg(L, phase, cycles)}{nodes}</svg>')

def _render(args):
    svg, path = args
    import cairosvg
    cairosvg.svg2png(bytestring=svg.encode(), write_to=path)
    return path

# =============================================================== swatches
def swatch_sheet(out, names, mode):
    """PNG with one row per palette on the chosen background, so the user sees real colors."""
    base = MODES[mode]
    rows = []
    for n in (names or list(PALETTES)):
        if n in PALETTES:
            rows.append((PALETTES[n][0], PALETTES[n][1 if mode == "light" else 2]))
        else:
            rows.append(("Custom", [norm_hex(c) for c in n.split(",")]))
    h = 100 * len(rows) + 30
    parts = [f'<rect width="980" height="{h}" fill="{base["bg"]}"/>']
    for i, (n, cols) in enumerate(rows):
        y = 30 + i * 100
        label = f"{i + 1}. {n}"
        fs = min(28, 28 * 280 / max(1, text_width(label, "Poppins", 28, True)))
        parts.append(txt(30, y + 40, label, fs, "Poppins", base["text"]))
        for j, c in enumerate(cols):
            x = 330 + j * 155
            parts.append(f'<circle cx="{x + 30}" cy="{y + 30}" r="30" fill="{c}"/>'
                         f'<rect x="{x + 70}" y="{y + 18}" width="64" height="24" rx="12" fill="{c}" opacity="0.35"/>'
                         + txt(x + 30, y + 82, c, 14, "Poppins", base["muted"], bold=False, anchor="middle"))
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="980" height="{h}">{"".join(parts)}</svg>'
    _render((svg, out))
    print(f"swatches ({mode}) -> {out}")

def encode_gif(frame_dir, fps, out, max_mb, W):
    pat = os.path.join(frame_dir, "f_%04d.png")
    pal = os.path.join(frame_dir, "pal.png")
    tmp = os.path.join(frame_dir, "raw.gif")
    attempts = [(256, 0, 1.0), (192, 20, 1.0), (128, 40, 1.0), (128, 60, 0.85), (96, 80, 0.75)]
    for colors, lossy, scale in attempts:
        sc = f"scale={int(W * scale) // 2 * 2}:-2:flags=lanczos," if scale < 1 else ""
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", pat,
                        "-vf", f"{sc}palettegen=max_colors={colors}:stats_mode=full", pal], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", pat, "-i", pal,
                        "-lavfi", f"{sc[:-1] + '[x];[x][1:v]' if sc else ''}paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                        "-loop", "0", tmp], check=True)
        if shutil.which("gifsicle"):
            subprocess.run(["gifsicle", "-O3", "--no-warnings"] + ([f"--lossy={lossy}"] if lossy else []) + [tmp, "-o", out], check=True)
        else:
            shutil.copy(tmp, out)
        mb = os.path.getsize(out) / 1e6
        print(f"  encoded: {colors} colors, lossy {lossy}, scale {scale:.0%} -> {mb:.2f} MB")
        if mb <= max_mb:
            return mb, scale
    warn(f"GIF is still above {max_mb} MB; reduce steps, seconds or fps")
    return mb, scale

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--preview")
    ap.add_argument("--gif")
    ap.add_argument("--svg", help="also write the first frame as SVG")
    ap.add_argument("--fps", type=int, default=16)
    ap.add_argument("--seconds", type=float, default=0, help="loop length; 0 = auto from step count")
    ap.add_argument("--max-mb", type=float, default=5.0)
    ap.add_argument("--icons", nargs="+")
    ap.add_argument("--palettes", action="store_true")
    ap.add_argument("--styles", action="store_true")
    ap.add_argument("--swatches", help="write a PNG sheet of palettes")
    ap.add_argument("--swatch-names", nargs="*", help="palette keys or custom 'hex,hex,..' lists (default: all)")
    ap.add_argument("--mode", default="light", choices=["light", "dark"], help="background for --swatches")
    a = ap.parse_args()

    if a.icons:
        return search_icons(a.icons)
    if a.palettes:
        for k, (name, lc, dc) in PALETTES.items():
            tag = "premium" if k in PREMIUM else "       "
            print(f"{k:18s} {tag} {name:25s} light {' '.join(lc)} | dark {' '.join(dc)}")
        return
    if a.styles:
        for k, v in STYLES.items():
            print(f"{k:10s} {v['desc']}")
        return
    if a.swatches:
        return swatch_sheet(a.swatches, a.swatch_names, a.mode)
    if not a.spec:
        ap.error("spec required")
    spec = json.load(open(a.spec))
    L = layout(spec)
    static, nodes = static_svg(L, spec), nodes_svg(L)
    max_slots = max(s["nslots"] for s in L["sections"])
    seconds = a.seconds or max(2.5, min(6.0, 0.5 * max_slots))
    nframes = max(8, round(seconds * a.fps))
    cycles = max(1, round(46 * seconds / 14.0))  # ~46 px/s dot speed; integer cycles = seamless loop

    if a.svg:
        open(a.svg, "w").write(frame_svg(L, static, nodes, 0.0, cycles))
    if a.preview:
        _render((frame_svg(L, static, nodes, 0.35, cycles), a.preview))
        print(f"preview -> {a.preview}")
    if a.gif:
        d = tempfile.mkdtemp(prefix="lnk_")
        jobs = [(frame_svg(L, static, nodes, i / nframes, cycles), os.path.join(d, f"f_{i:04d}.png"))
                for i in range(nframes)]
        print(f"rendering {nframes} frames ({seconds:.1f}s loop @ {a.fps} fps)...")
        with ProcessPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
            list(ex.map(_render, jobs))
        mb, scale = encode_gif(d, a.fps, a.gif, a.max_mb, L["W"])
        shutil.rmtree(d, ignore_errors=True)
        print(f"gif -> {a.gif} ({mb:.2f} MB, {int(L['W'] * scale)}x{int(L['H'] * scale)}, loops forever)")
    for w in dict.fromkeys(WARN):
        print("WARNING:", w)

if __name__ == "__main__":
    main()
