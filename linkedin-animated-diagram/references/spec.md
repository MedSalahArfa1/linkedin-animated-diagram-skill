# Spec format

A spec is one JSON object. Only `title` and `sections` are required.

```json
{
  "mode": "dark",
  "style": "tech",
  "palette": "blue-teal",
  "lang": "en",
  "background": {"icons": ["database", "brain", "search"]},
  "author": {"name": "Jane Doe", "linkedin": "https://www.linkedin.com/in/janedoe", "avatar": "/mnt/user-data/uploads/photo.jpg"},
  "title": [{"text": "RAG ", "color": "s0"}, {"text": "VS ", "color": "text"}, {"text": "CAG", "color": "s1"}],
  "subtitle": "One-line takeaway",
  "sections": [
    {
      "heading": "RAG (Retrieval-Augmented Generation)",
      "steps": [
        {"label": "User Query", "icon": "user"},
        [{"label": "Vector Search", "icon": "database"}, {"label": "Keyword Search", "icon": "search"}],
        {"label": "LLM Answer", "icon": "brain"}
      ]
    }
  ]
}
```

## Fields

| Field | Notes |
|---|---|
| `mode` | `"light"` (default) or `"dark"`. Sets background, text and the palette variant. |
| `style` | `clean` (default), `tech`, `code`, `editorial`, `bold`, `soft`. Fonts, node shape and node style. See `--styles`. |
| `palette` | A palette key (`--palettes`, 21 presets of which 8 premium; each has a light and a dark variant), a list of 1 to 4 hex codes, or `{"colors": [...], "bg": "#..", "text": "#.."}` to also set background/text. |
| `lang` | Language code of the text (`en`, `fr`, `ar`, ...). `ar`/`fa`/`ur` switch to right-to-left layout and the Tajawal font. Also selects the built-in CTA wording. |
| `background` | `icons`: Lucide names scattered large and very faint near the edges. `glows`: soft blurred circles in the top-left and bottom-right corners using the first two palette colors (default `true`, `false` to remove). `intensity` (icon strength, default 1.0), `seed` (change for a different arrangement). |
| `author` | Author card at the bottom, above the CTA (rounded rectangle, animated dashed border in the first palette color): `name`, `linkedin` (any form of the profile URL; shown as `linkedin.com/in/...` with an "in" mark), optional `avatar` (local JPG/PNG/WEBP, auto-cropped to a circle; without it no circle is drawn and the name/link are centered), optional `tagline`. |
| `title` | Plain string, or a list of segments `{text, color}` in reading order. Put spaces inside segment text (`"RAG "`). Auto-sized. |
| `subtitle` | Optional, up to 2 lines, muted color. |
| `sections` | 1 to 3. Each gets its own color, dashed divider and heading. |
| `sections[].heading` | Optional, one line, always centered (auto-shrinks). |
| `sections[].color` | Optional hex to override the palette for that section. |
| `sections[].columns` | Optional; nodes per row (default up to 4). The flow snakes row by row. |
| `sections[].steps` | Ordered list. A step is `{label, icon}`; a two-item list is a parallel group (fork then merge). |
| `steps[].color` | Optional accent for one step: `"s1"`, `"s2"`... (palette colors) or a hex. Use it to highlight key stages, especially in single-section diagrams where only the first palette color would otherwise appear. |
| `cta` | `true` (default: Like / Comment / Repost / Follow in `lang`), `false` to hide, or four custom words in that order. |
| `footer` | Optional small line above the CTA. |
| `overrides` | Advanced: raw theme keys (`bg`, `text`, `muted`, `node_style`, `node_shape`, `label_color`, `title_font`, `body_font`). |
| `canvas` | `"4:5"` (default, 1080x1350), `"1:1"`, `"16:9"`. |

## Color references
In `title` segments: a hex value, `"text"`, `"muted"`, or `"s0"`, `"s1"`, `"s2"`, `"s3"` for the section
colors followed by the remaining palette colors.

## Sizing guidance (with badge and CTA)
- 1 section: up to 10 steps comfortably.
- 2 sections: up to 7 steps each, one fork per section at most.
- 3 sections: up to 5 steps each, no forks.
Beyond this it still renders, but nodes and labels get small. Prefer splitting into two posts.
