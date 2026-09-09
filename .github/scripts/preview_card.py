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
        "bg": "#0d1117", "border": "#30363d", "header": "#79c0ff",
        "dash": "#8b949e", "section": "#d2a8ff", "label": "#ff7b72",
        "value": "#c9d1d9", "art": "#58a6ff",
    },
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "header": "#0969da",
        "dash": "#57606a", "section": "#8250df", "label": "#cf222e",
        "value": "#24292f", "art": "#0969da",
    },
}

FONT_SIZE = 14
LINE_HEIGHT = 20
CHAR_W = 8.4
PAD = 24
ART_X = PAD
STATS_X = PAD + max(len(l) for l in ASCII_ART) * CHAR_W + 40


def build_stat_lines(values):
    return [
        "kkura@git",
        "----------",
        "OS:      Windows 11, iOS, Ubuntu",
        f"Uptime:  {values['UPTIME']}",
        "Kernel:  Data Quality / IT Support",
        "IDE:     VSCode",
        "",
        "- Tech stack ------------------------------------------",
        "Programming:        Python, C",
        "Web:                HTML, CSS, JavaScript",
        "Data:                SQL, SQLite, MS SQL Server, Firebase",
        "Analytics:          R, Excel",
        "Tools:              JIRA",
        "Cloud:              AWS",
        "Human:              English, Tagalog",
        "",
        "- Interests -------------------------------------------",
        "Software:           Adobe Photoshop, FL Studio",
        "Interactive Media:  Minecraft, Rhythm Games",
        "Creative:           Music Production, Drumming",
        "",
        "- Contact ---------------------------------------------",
        "Email:              jfonse01@uoguelph.ca",
        "LinkedIn:           joshuacfonseca",
        "Discord:            cqrd",
        "",
        "- GitHub Stats ------------------------------------------",
        f"Personal Repos: {values['PERSONAL_REPOS']} | Other Repos: {values['OTHER_REPOS']}",
        f"Personal Commits: {values['PERSONAL_COMMITS']} | Other Commits: {values['OTHER_COMMITS']}",
        f"Lines of Code: {values['TOTAL_LOC']} ({values['LOC_ADDED']}++, {values['LOC_DELETED']}--)",
    ]


def classify_line(text, colors):
    if text == "kkura@git":
        return [(text, colors["header"])]
    if text and set(text) <= {"-"}:
        return [(text, colors["dash"])]
    if text.startswith("- "):
        return [(text, colors["section"])]
    if text == "":
        return [("", colors["value"])]
    if " | " in text:
        segs = []
        parts = text.split(" | ")
        for i, part in enumerate(parts):
            if ":" in part:
                lbl, val = part.split(":", 1)
                segs.append((lbl + ":", colors["label"]))
                segs.append((val, colors["value"]))
            else:
                segs.append((part, colors["value"]))
            if i < len(parts) - 1:
                segs.append((" | ", colors["dash"]))
        return segs
    if ":" in text:
        lbl, val = text.split(":", 1)
        return [(lbl + ":", colors["label"]), (val, colors["value"])]
    return [(text, colors["value"])]


def render_svg(values, theme_name):
    colors = THEMES[theme_name]
    stat_lines = build_stat_lines(values)
    n_lines = max(len(ASCII_ART), len(stat_lines))
    width = int(STATS_X + max(len(l) for l in stat_lines) * CHAR_W + PAD)
    height = int(n_lines * LINE_HEIGHT + PAD * 2)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="SFMono-Regular, Consolas, '
        f'\'Liberation Mono\', Menlo, monospace" font-size="{FONT_SIZE}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="8" '
        f'fill="{colors["bg"]}" stroke="{colors["border"]}"/>',
    ]

    art_y = PAD + FONT_SIZE
    parts.append(f'<text x="{ART_X}" y="{art_y}" fill="{colors["art"]}" xml:space="preserve">')
    for i, line in enumerate(ASCII_ART):
        dy = 0 if i == 0 else LINE_HEIGHT
        parts.append(f'<tspan x="{ART_X}" dy="{dy}">{escape(line)}</tspan>')
    parts.append("</text>")

    stats_y = PAD + FONT_SIZE
    parts.append(f'<text x="{STATS_X}" y="{stats_y}" xml:space="preserve">')
    for i, line in enumerate(stat_lines):
        dy = 0 if i == 0 else LINE_HEIGHT
        segs = classify_line(line, colors)
        tspan_open = f'<tspan x="{STATS_X}" dy="{dy}">' if i > 0 else f'<tspan x="{STATS_X}">'
        parts.append(tspan_open)
        for text, color in segs:
            parts.append(f'<tspan fill="{color}">{escape(text)}</tspan>')
        parts.append("</tspan>")
    parts.append("</text>")

    parts.append("</svg>")
    return "\n".join(parts)


if __name__ == "__main__":
    with open("preview_dark.svg", "w") as f:
        f.write(render_svg(SAMPLE_VALUES, "dark"))
    with open("preview_light.svg", "w") as f:
        f.write(render_svg(SAMPLE_VALUES, "light"))
    print("Wrote preview_dark.svg and preview_light.svg — open either in a browser to view.")
