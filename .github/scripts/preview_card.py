"""
Local preview tool — renders dark/light SVGs using placeholder numbers,
with NO network calls and NO token required. Use this to check how your
ASCII art and layout look before running the real workflow.

Usage:
    python3 .github/scripts/preview_card.py

Then open preview_dark.svg / preview_light.svg in a browser or VS Code
(right-click > Open Preview, if you have an SVG preview extension).
"""

from xml.sax.saxutils import escape

# ---- Paste your ASCII_ART list here to preview it ---------------------------
ASCII_ART = [
    "                .:^^^^:.",
    "             .:^        ^:.",
    "           .:^            ^:.",
    "          :^                ^:",
    "         :^      (o)         ^:",
    "        :^                    ^:",
    "        ^:                    :^",
    "    (o) ^:                    :^ (o)",
    "        :^,                  ,^:",
    "         ':^,              ,^:'",
    "           ':^,,        ,,^:'",
    "             ':^^,,,,,,^^:'",
    "                '':::::''",
]
# -------------------------------------------------------------------------------

# Fake numbers just for layout/color preview
SAMPLE_VALUES = {
    "UPTIME": "23 years, 6 months, 3 days",
    "PERSONAL_REPOS": 12,
    "OTHER_REPOS": 4,
    "PERSONAL_COMMITS": "1,234",
    "OTHER_COMMITS": "56",
    "TOTAL_LOC": "45,678",
    "LOC_ADDED": "50,000",
    "LOC_DELETED": "4,322",
}

THEMES = {
    "dark": {
        "bg": "#0d1117", "border": "#30363d", "header": "#eb6f92",
        "header_at": "#ffffff", "dash": "#8b949e", "section": "#ffffff",
        "label": "#eb6f92", "value": "#c9d1d9", "art": "#eb6f92",
    },
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "header": "#eb6f92",
        "header_at": "#24292f", "dash": "#57606a", "section": "#24292f",
        "label": "#eb6f92", "value": "#24292f", "art": "#eb6f92",
    },
}

FONT_SIZE = 14
LINE_HEIGHT = 20
CHAR_W = 8.4
PAD = 24
GAP_CHARS = 2         # min gap (in chars) between the longest label and its value
SECTION_DASH_MIN = 4  # shortest a section-header dash run is allowed to shrink to


def esc(s):
    return escape(str(s))


def build_blocks(values):
    """The whole card, described as a sequence of typed blocks.
    'fields' blocks get their value column aligned to the longest label
    in that block. 'pairs' blocks align into four columns."""
    return [
        {"type": "header", "text": "kkura@git"},
        {"type": "dash", "text": "----------"},
        {"type": "fields", "items": [
            ("OS:", "Windows 11, iOS, Ubuntu"),
            ("Uptime:", values["UPTIME"]),
            ("Kernel:", "Data Quality / IT Support"),
            ("IDE:", "VSCode"),
        ]},
        {"type": "section", "label": "Tech stack"},
        {"type": "fields", "items": [
            ("Core languages:", "Python, C"),
            ("Frontend languages:", "HTML, CSS, JavaScript"),
            ("Databases:", "SQL, SQLite, MS SQL Server, Firebase"),
            ("Data Analytics:", "R, Excel"),
            ("Project Management Tools:", "JIRA, GitLab"),
            ("Cloud Platforms:", "AWS"),
        ]},
        {"type": "section", "label": "Interests"},
        {"type": "fields", "items": [
            ("Software:", "Adobe Photoshop, FL Studio"),
            ("Interactive Media:", "Minecraft, Rhythm Games"),
            ("Creative:", "Music Production, Drumming"),
        ]},
        {"type": "section", "label": "Contact Info"},
        {"type": "fields", "items": [
            ("Email:", "jfonse01@uoguelph.ca"),
            ("LinkedIn:", "joshuacfonseca"),
            ("Discord:", "cqrd"),
        ]},
        {"type": "section", "label": "GitHub Contributions"},
        {"type": "pairs", "rows": [
            [("Personal Repos:", str(values["PERSONAL_REPOS"])), ("Other Repos:", str(values["OTHER_REPOS"]))],
            [("Personal Commits:", values["PERSONAL_COMMITS"]), ("Other Commits:", values["OTHER_COMMITS"])],
        ]},
        {"type": "fields", "items": [
            ("Lines of Code:", f"{values['TOTAL_LOC']} ({values['LOC_ADDED']}++, {values['LOC_DELETED']}--)"),
        ]},
    ]


def label_column_width(blocks):
    """Global label-column width (in chars), shared by every 'fields' block so
    every label/value pair lines up at the same x position across the WHOLE
    card, not just within its own section."""
    widths = [len(l) for b in blocks if b["type"] == "fields" for l, v in b["items"]]
    return (max(widths) if widths else 0) + GAP_CHARS


def content_width_chars(blocks, label_col):
    """How wide (in chars) the stats column's content is, overall. Section
    header dash-runs are stretched or shrunk to reach exactly this width, so
    every kind of row - fields, pairs, and section dividers - lines up on the
    same right edge, the way Andrew6rant's card does."""
    chars = 0
    for b in blocks:
        if b["type"] in ("header", "dash"):
            chars = max(chars, len(b["text"]))
        elif b["type"] == "fields":
            for l, v in b["items"]:
                chars = max(chars, label_col + len(v))
        elif b["type"] == "pairs":
            # Both columns render at equal width (see render_svg), so the
            # pair needs 2x whichever side (label+gap+value) is wider.
            col1_chars = max(len(r[0][0]) for r in b["rows"]) + GAP_CHARS + max(len(r[0][1]) for r in b["rows"])
            col2_chars = max(len(r[1][0]) for r in b["rows"]) + GAP_CHARS + max(len(r[1][1]) for r in b["rows"])
            chars = max(chars, 2 * max(col1_chars, col2_chars))
    # make sure a long section label still fits with at least the minimum dashes
    for b in blocks:
        if b["type"] == "section":
            chars = max(chars, len(f"- {b['label']} ") + SECTION_DASH_MIN)
    return chars


def measure_width(blocks, ascii_art, stats_x_start, content_chars):
    art_chars = max(len(l) for l in ascii_art)
    return max(
        stats_x_start + int(content_chars * CHAR_W),
        PAD + int(art_chars * CHAR_W),
    ) + PAD


def count_lines(blocks, ascii_art):
    n = 0
    for b in blocks:
        if b["type"] == "fields":
            n += len(b["items"])
        elif b["type"] == "pairs":
            n += len(b["rows"])
        else:
            n += 1
    return max(n, len(ascii_art))


def render_svg(values, theme_name):
    colors = THEMES[theme_name]
    art_x = PAD
    stats_x = PAD + max(len(l) for l in ASCII_ART) * CHAR_W + 40

    blocks = build_blocks(values)
    label_col = label_column_width(blocks)
    content_chars = content_width_chars(blocks, label_col)
    width = measure_width(blocks, ASCII_ART, stats_x, content_chars)
    n_lines = count_lines(blocks, ASCII_ART)
    height = int(n_lines * LINE_HEIGHT + PAD * 2)
    right_edge = stats_x + content_chars * CHAR_W

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="SFMono-Regular, Consolas, '
        f'\'Liberation Mono\', Menlo, monospace" font-size="{FONT_SIZE}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="8" '
        f'fill="{colors["bg"]}" stroke="{colors["border"]}"/>',
    ]

    art_y = PAD + FONT_SIZE
    parts.append(f'<text x="{art_x}" y="{art_y}" fill="{colors["art"]}" xml:space="preserve">')
    for i, line in enumerate(ASCII_ART):
        dy = 0 if i == 0 else LINE_HEIGHT
        parts.append(f'<tspan x="{art_x}" dy="{dy}">{esc(line)}</tspan>')
    parts.append("</text>")

    # Stats column: every row gets its own absolute y (rather than chained
    # relative dy). This lets section dividers be drawn as real <line>
    # elements - pixel-exact against the value column's right_edge, instead
    # of a run of "-" characters whose total width depends on the renderer's
    # font metrics actually matching CHAR_W.
    stats_y = PAD + FONT_SIZE
    line_i = 0

    def next_y():
        nonlocal line_i
        y = stats_y + line_i * LINE_HEIGHT
        line_i += 1
        return y

    for b in blocks:
        if b["type"] == "header":
            y = next_y()
            name, at, rest = b["text"].partition("@")
            parts.append(
                f'<text x="{stats_x}" y="{y}">'
                f'<tspan fill="{colors["header"]}">{esc(name)}</tspan>'
                f'<tspan fill="{colors["header_at"]}">{esc(at)}</tspan>'
                f'<tspan fill="{colors["header"]}">{esc(rest)}</tspan>'
                f'</text>'
            )

        elif b["type"] == "dash":
            y = next_y()
            parts.append(f'<text x="{stats_x}" y="{y}" fill="{colors["dash"]}">{esc(b["text"])}</text>')

        elif b["type"] == "section":
            y = next_y()
            prefix = f"- {b['label']} "
            prefix_end_x = stats_x + len(prefix) * CHAR_W
            parts.append(f'<text x="{stats_x}" y="{y}" fill="{colors["section"]}">{esc(prefix)}</text>')
            if prefix_end_x < right_edge:
                line_y = y - FONT_SIZE * 0.32
                parts.append(
                    f'<line x1="{prefix_end_x}" y1="{line_y}" x2="{right_edge}" y2="{line_y}" '
                    f'stroke="{colors["dash"]}" stroke-width="1.2"/>'
                )

        elif b["type"] == "fields":
            for l, v in b["items"]:
                y = next_y()
                parts.append(
                    f'<text x="{stats_x}" y="{y}">'
                    f'<tspan fill="{colors["label"]}">{esc(l)}</tspan>'
                    f'<tspan x="{right_edge}" text-anchor="end" fill="{colors["value"]}">{esc(v)}</tspan>'
                    f'</text>'
                )

        elif b["type"] == "pairs":
            mid_edge = stats_x + (content_chars / 2) * CHAR_W
            x_v1_right = mid_edge - GAP_CHARS * CHAR_W
            x_l2 = mid_edge
            for row in b["rows"]:
                y = next_y()
                (l1, v1), (l2, v2) = row
                parts.append(
                    f'<text x="{stats_x}" y="{y}">'
                    f'<tspan fill="{colors["label"]}">{esc(l1)}</tspan>'
                    f'<tspan x="{x_v1_right}" text-anchor="end" fill="{colors["value"]}">{esc(v1)}</tspan>'
                    f'<tspan x="{x_l2}" fill="{colors["label"]}">{esc(l2)}</tspan>'
                    f'<tspan x="{right_edge}" text-anchor="end" fill="{colors["value"]}">{esc(v2)}</tspan>'
                    f'</text>'
                )

    parts.append("</svg>")
    return "\n".join(parts)


if __name__ == "__main__":
    with open("preview_dark.svg", "w") as f:
        f.write(render_svg(SAMPLE_VALUES, "dark"))
    with open("preview_light.svg", "w") as f:
        f.write(render_svg(SAMPLE_VALUES, "light"))
    print("Wrote preview_dark.svg and preview_light.svg — open either in a browser to view.")