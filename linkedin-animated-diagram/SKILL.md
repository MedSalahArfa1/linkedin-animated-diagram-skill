---
name: linkedin-animated-diagram
description: Turn any subject into a ready-to-post animated LinkedIn GIF in the popular infographic style, with icon nodes connected by flowing dotted lines (like "RAG vs CAG" or "How X works" posts). The user only gives a topic; Claude asks a few quick personalization questions (name, LinkedIn link, profile photo, light or dark background, language, color palette), then researches the subject, designs the flow, renders a looping 1080x1350 GIF with a Like / Comment / Repost / Follow call to action, and writes the caption. Supports English, French, Arabic (right-to-left) and other Latin-script languages. Use this skill whenever the user asks for an animated diagram, animated infographic, moving-lines GIF, LinkedIn visual, pipeline/workflow/process animation, "X vs Y" comparison graphic, or says something like "make a LinkedIn post about [topic]" with a visual, even if they don't say GIF or animation.
---

# LinkedIn Animated Diagram

Produces one looping GIF (portrait 4:5, 1080x1350) showing a process as icon nodes linked by animated
dotted connectors, a "pulse" ripple walking through the steps, a background of soft glowing circles in
two opposite corners plus very faint subject icons, and at the bottom an author card (rounded rectangle with a moving dashed border) above a
centered Like / Comment / Repost / Follow call to action. The user gives a subject; you handle
content, structure and design after a short intake.

The rendering is deterministic: you write a JSON spec and `scripts/render.py` does layout, icons, fonts,
Arabic shaping, animation and GIF compression. Your job is the thinking: accurate content, a clear flow,
a design that fits the subject.

`SKILL_DIR` below means the folder containing this SKILL.md. Paths like `/home/claude` (working files) and
`/mnt/user-data/outputs` (deliverables, shown with `present_files`) are for Claude.ai. In other environments
such as Claude Code, use a working folder and an output folder in the current project instead, and tell the
user where the GIF was saved.

## Workflow

### 1. Setup (once per session)
```bash
bash SKILL_DIR/scripts/setup.sh
```
Installs the renderer, GIF tools, fonts (Poppins, Bebas Neue, DM Serif Display, IBM Plex Mono, Tajawal for
Arabic) and ~2,300 Lucide icons. Warnings are non-fatal.

### 2. Intake (two quick rounds)
Personal choices change the final file, so collect them before designing. If an answer is already known
from earlier in the conversation (or from what you know about the user), confirm it instead of asking from
scratch, and reuse all answers for later diagrams in the same conversation. Never invent a name or link.

**Round 1:** ask with the interactive options tool (`ask_user_input_v0`) when available; it allows at
most 3 questions, so use exactly these:
1. **Badge.** If name and LinkedIn link are known, show them in the question and offer:
   "Name + link + my photo" / "Name + link, no photo" / "Change name or link" / "No badge".
   If unknown, ask for name and LinkedIn link in the message text just before the tool, and offer:
   "Add my photo" / "No photo" / "No badge".
2. **Background:** "Light" / "Dark".
3. **Language:** the user's own language first, then English / French / Arabic as relevant, plus
   "Other (I'll type it)".

Without that tool, ask the same things in one short message.

**Round 2:** palette, shown on the chosen background:
- Pick the 3 palettes whose colors best fit the subject (`render.py --palettes`). All are named by color.
  - **Premium** (refined, high-contrast pairings that look at home in the LinkedIn feed): LinkedIn Blue,
    Navy & Gold, Indigo & Coral, Emerald & Slate, Burgundy & Gold, Teal & Coral, Plum & Rose,
    Charcoal & Electric Blue.
  - **Standard:** Blues, Teal & Cyan, Blue & Teal, Greens, Green & Brown, Reds & Oranges, Amber & Gold,
    Purples, Pink & Purple, Blue & Orange, Red & Purple, Multicolor, Grayscale.

  For professional subjects (AI, tech, business, careers) include at least 2 premium palettes among the 3.
  Two-color premium pairs (e.g. Indigo & Coral) suit "X vs Y" comparisons: each side gets its own color.
  Mark premium options as such when you offer them. Render and present a swatch sheet:
  ```bash
  python3 SKILL_DIR/scripts/render.py --swatches /mnt/user-data/outputs/palettes.png --mode dark --swatch-names indigo-coral navy-gold blue-teal
  ```
- **If the user wants their photo and hasn't uploaded it yet:** don't use the options tool (a tapped answer
  can't carry an attachment). Ask in plain text: "Attach your profile photo and tell me the palette number,
  or type your own hex codes."
- **Otherwise:** ask with the options tool: the 3 palette names plus "Custom (I'll type hex codes)".
- **Custom palettes:** accept 1 to 4 hex codes in any common form (`#FF6B35`, `ff6b35`, `#f63`), or colors
  described in words (translate to hex yourself and say which codes you used). Section 1 uses color 1,
  section 2 color 2, extra colors can color title words (`s1`, `s2`). If the renderer warns about low
  contrast on the chosen background, tell the user and propose the nearest readable shade instead of
  silently changing their colors.

**Profile photo:** uploads land in `/mnt/user-data/uploads/`. View the image to confirm it is a usable
portrait (JPG, PNG or WEBP). The renderer crops it to a circle, biased toward the top of the image where
faces usually are. If it's clearly not a portrait or too small/blurry, say so and offer the name-only badge.
Without a photo, the author card holds just the name and link, centered, with no circle.

### 3. Shape the content
Write all text in the chosen language. If the subject involves facts you are not sure of (recent tools,
specific architectures, numbers), search first. Then choose a structure:

- **One process** ("How YOLO deployment works") → 1 section, 6 to 10 steps.
- **Comparison** ("RAG vs CAG") → 2 sections, 5 to 8 steps each, at a parallel level of detail.
- **Three variants** ("3 ways to fine-tune") → 3 sections, 3 to 5 steps each.

Step labels: 1 to 3 words ("Embed Query", "Vector DB"). Use a parallel group (two steps side by side) only
where the real process forks, at most one or two per section. Title: 2 to 5 punchy words; optional
one-line subtitle stating the takeaway. In Arabic, keep standard technical acronyms in Latin (YOLO, RAG,
API) where that's how practitioners write them.

### 4. Design: style, background icons, step icons
- **Style** (`render.py --styles`): `clean` (AI/ML, general), `tech` (infra, cloud, GPUs, security, IoT),
  `code` (DevOps, backend), `editorial` (business, careers, research), `bold` (hot takes, myths vs facts),
  `soft` (learning, wellbeing, nature). All styles work in light and dark mode.
- **Background icons:** choose 2 to 4 Lucide icons that evoke the subject (e.g. `flame`, `trees`, `cctv`
  for forest fire detection; `database`, `brain`, `search` for RAG). They are scattered large and very
  faint around the edges. Two soft blurred glows in the top-left and bottom-right corners take the first
  two palette colors (in a comparison, each side's color). There are no other background shapes or lines.
  Use `"intensity"` (0.5 to 1.5) only if the preview looks too busy or too empty.
- **Accent steps:** in a single-section diagram only the first palette color is used by default, so give
  2 to 4 key steps `"color": "s1"` (the palette's second color) to make the whole palette visible and draw
  the eye to the stages that matter (e.g. the detection and alert steps).
- **Icons for steps:** verify Lucide names before using them:
  ```bash
  python3 SKILL_DIR/scripts/render.py --icons database brain fire camera
  ```

### 5. Write the spec and preview
Write the spec to `/home/claude/<slug>.json` (format: `references/spec.md`; example:
`assets/example-rag-vs-cag.json`), then:
```bash
python3 SKILL_DIR/scripts/render.py /home/claude/<slug>.json --preview /home/claude/<slug>.png
```
**Always view the preview before rendering the GIF.** Check: no overlapping or truncated text ("…"), title
readable, title and section headings centered, flow order correct, background icons faint and not
behind text, photo cropped well, author card centered just above the four CTA buttons.
Read every WARNING line. Fix the spec and preview again until clean. If a fork row is cramped, drop the
subtitle or a step rather than shrinking everything.

### 6. Render and deliver
```bash
python3 SKILL_DIR/scripts/render.py /home/claude/<slug>.json --gif /mnt/user-data/outputs/<slug>.gif
```
Seamless loop, 2.5 to 6 s at 16 fps, encoded with up to 256 colors and fine dithering so the corner glows
stay smooth, and compressed under `--max-mb` (default 5; typically about 1 to 1.5 MB). Present the GIF with `present_files`.

### 7. Caption
In the reply, give a ready-to-paste LinkedIn caption in the chosen language: a hook line, 3 to 5 short lines
explaining the key insight, a question to spark comments, and 3 to 5 hashtags. Remind the user to upload
the GIF as a normal image in the post (inside a PDF/document carousel it won't animate).

## Languages
Built-in CTA wording for en, fr, ar, es, de, it, pt, nl, tr. For another Latin-script language, pass the
four translated words in this order: `"cta": ["Like", "Comment", "Repost", "Follow"]`. Arabic
(`"lang": "ar"`) switches to the Tajawal font and a right-to-left layout automatically (flow and CTA start
on the right, photo on the right of the name inside the author card). Scripts
the fonts don't cover (Chinese, Japanese, Cyrillic, Hebrew...) are not supported: say so and offer
English, French or Arabic.

## Limits
- 1 to 3 sections, up to 12 steps per section, parallel groups of exactly 2.
- Arabic short vowel marks (harakat) are dropped for clean rendering.
- Optional flags: `--fps`, `--seconds`, `--max-mb`, `--svg path` (still SVG of frame 0).
