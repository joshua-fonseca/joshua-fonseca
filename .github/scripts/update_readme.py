"""
Generates dark_mode.svg and light_mode.svg — a fastfetch-style stats card,
colored to match GitHub's own dark/light theme palettes.

Requires:
  - ACCESS_TOKEN env var: a classic GitHub PAT with `repo` + `read:user` scopes
  - Run from the root of the repo (writes dark_mode.svg / light_mode.svg there)

Pipeline:
  1. Query GitHub's GraphQL API for owned repos + repos contributed to.
  2. Count commits per repo via GraphQL (no cloning needed for this part).
  3. For lines added/deleted (not exposed by the API), shallow-clone each repo
     and run `git log --numstat`, caching scanned commit SHAs in
     .github/scripts/loc_cache.json so repeat runs only scan new commits.
  4. Render two SVGs (dark + light) with the computed values.

README setup: this script does NOT touch README.md. Add this once, anywhere
you want the card to appear:

    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="dark_mode.svg">
      <source media="(prefers-color-scheme: light)" srcset="light_mode.svg">
      <img alt="kkura's GitHub stats" src="dark_mode.svg">
    </picture>
"""

import os
import re
import json
import shutil
import subprocess
import calendar
from datetime import date
from xml.sax.saxutils import escape

import requests

# ---- CONFIG: edit these for your account ----------------------------------
BIRTH_DATE = date(2003, 3, 5)  # for the "Uptime" field

AUTHOR_EMAILS = {
    "jfonse01@uoguelph.ca",
    "joshuacfonseca@gmail.com",
    "96248012+joshua-fonseca@users.noreply.github.com",
    # "your-username@users.noreply.github.com",
}

EXCLUDE_REPOS = set()  # e.g. {"owner/some-huge-vendored-repo"}
CACHE_PATH = ".github/scripts/loc_cache.json"

# Left-hand ASCII art. Replace this list with your own — one string per line.
# Keep lines to roughly 34 characters or less so they fit the art column.
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
# -----------------------------------------------------------------------------

API_URL = "https://api.github.com/graphql"
TOKEN = os.environ["ACCESS_TOKEN"]
HEADERS = {"Authorization": f"bearer {TOKEN}"}


def gql(query, variables=None):
    r = requests.post(
        API_URL, json={"query": query, "variables": variables or {}}, headers=HEADERS
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def get_viewer_id():
    d = gql("{ viewer { id login } }")
    return d["viewer"]["id"], d["viewer"]["login"]


def list_repos(affiliations):
    repos, cursor = [], None
    q = """
    query($cursor: String, $affiliations: [RepositoryAffiliation]) {
      viewer {
        repositories(first: 100, after: $cursor, ownerAffiliations: $affiliations, isFork: false) {
          pageInfo { hasNextPage endCursor }
          nodes { nameWithOwner isPrivate defaultBranchRef { name } }
        }
      }
    }
    """
    while True:
        d = gql(q, {"cursor": cursor, "affiliations": affiliations})
        conn = d["viewer"]["repositories"]
        repos += [n for n in conn["nodes"] if n["defaultBranchRef"]]
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    return repos


def list_contributed_repos():
    repos, cursor = [], None
    q = """
    query($cursor: String) {
      viewer {
        repositoriesContributedTo(first: 100, after: $cursor, contributionTypes: [COMMIT], includeUserRepositories: false) {
          pageInfo { hasNextPage endCursor }
          nodes { nameWithOwner isPrivate defaultBranchRef { name } }
        }
      }
    }
    """
    while True:
        d = gql(q, {"cursor": cursor})
        conn = d["viewer"]["repositoriesContributedTo"]
        repos += [n for n in conn["nodes"] if n["defaultBranchRef"]]
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    return repos


def commit_count(name_with_owner, branch, user_id):
    owner, name = name_with_owner.split("/")
    q = """
    query($owner: String!, $name: String!, $branch: String!, $id: ID!) {
      repository(owner: $owner, name: $name) {
        ref(qualifiedName: $branch) {
          target { ... on Commit { history(author: { id: $id }) { totalCount } } }
        }
      }
    }
    """
    d = gql(q, {"owner": owner, "name": name, "branch": branch, "id": user_id})
    ref = d["repository"]["ref"]
    if not ref or not ref["target"]:
        return 0
    return ref["target"]["history"]["totalCount"]


def uptime_string(birth, today=None):
    today = today or date.today()
    years = today.year - birth.year
    months = today.month - birth.month
    days = today.day - birth.day
    if days < 0:
        months -= 1
        prev_month = today.month - 1 or 12
        prev_year = today.year if today.month != 1 else today.year - 1
        days += calendar.monthrange(prev_year, prev_month)[1]
    if months < 0:
        years -= 1
        months += 12
    return f"{years} years, {months} months, {days} days"


def clone_or_update(name_with_owner, workdir):
    path = os.path.join(workdir, name_with_owner.replace("/", "__"))
    url = f"https://x-access-token:{TOKEN}@github.com/{name_with_owner}.git"
    if os.path.isdir(path):
        subprocess.run(["git", "-C", path, "fetch", "--all", "-q"], check=False)
    else:
        subprocess.run(["git", "clone", "--quiet", url, path], check=False)
    return path


SHA_LINE = re.compile(r"^[0-9a-f]{40}\|")


def loc_for_repo(path, branch, cache, name_with_owner):
    entry = cache.get(name_with_owner, {"seen_shas": [], "added": 0, "deleted": 0})
    seen = set(entry["seen_shas"])
    added, deleted = entry["added"], entry["deleted"]

    log = subprocess.run(
        ["git", "-C", path, "log", f"origin/{branch}", "--no-merges",
         "--pretty=format:%H|%ae", "--numstat"],
        capture_output=True, text=True, check=False,
    ).stdout

    count_this = False
    for line in log.splitlines():
        if SHA_LINE.match(line):
            sha, email = line.split("|", 1)
            count_this = sha not in seen and email in AUTHOR_EMAILS
            seen.add(sha)
        elif count_this and line.strip():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                added += int(parts[0])
                deleted += int(parts[1])

    cache[name_with_owner] = {"seen_shas": list(seen), "added": added, "deleted": deleted}
    return added, deleted


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
            ("Core languages", "Python, C"),
            ("Frontend languages:", "HTML, CSS, JavaScript"),
            ("Databases:", "SQL, SQLite, MS SQL Server, Firebase"),
            ("Data Analytics:", "R, Excel"),
            ("Porject Management Tools:", "JIRA, Gitlab"),
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
    """Compute total SVG width from the widest rendered row."""
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


def render_svg(values, theme_name, themes, ascii_art):
    colors = themes[theme_name]
    art_x = PAD
    stats_x = PAD + max(len(l) for l in ascii_art) * CHAR_W + 40

    blocks = build_blocks(values)
    label_col = label_column_width(blocks)
    content_chars = content_width_chars(blocks, label_col)
    width = measure_width(blocks, ascii_art, stats_x, content_chars)
    n_lines = count_lines(blocks, ascii_art)
    height = int(n_lines * LINE_HEIGHT + PAD * 2)
    right_edge = stats_x + content_chars * CHAR_W

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="SFMono-Regular, Consolas, '
        f'\'Liberation Mono\', Menlo, monospace" font-size="{FONT_SIZE}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="8" '
        f'fill="{colors["bg"]}" stroke="{colors["border"]}"/>',
    ]

    # ASCII art column
    art_y = PAD + FONT_SIZE
    parts.append(f'<text x="{art_x}" y="{art_y}" fill="{colors["art"]}" xml:space="preserve">')
    for i, line in enumerate(ascii_art):
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


ASCII_ART_COLOR_KEY = "art"

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


def main():
    user_id, _login = get_viewer_id()

    personal_repos = list_repos(["OWNER"])
    other_repos = list_contributed_repos()

    personal_commits = sum(
        commit_count(r["nameWithOwner"], r["defaultBranchRef"]["name"], user_id)
        for r in personal_repos
    )
    other_commits = sum(
        commit_count(r["nameWithOwner"], r["defaultBranchRef"]["name"], user_id)
        for r in other_repos
    )

    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cache = json.load(f)

    workdir = "/tmp/loc_repos"
    os.makedirs(workdir, exist_ok=True)
    total_added = total_deleted = 0
    for r in personal_repos + other_repos:
        name = r["nameWithOwner"]
        if name in EXCLUDE_REPOS:
            continue
        branch = r["defaultBranchRef"]["name"]
        path = clone_or_update(name, workdir)
        a, d = loc_for_repo(path, branch, cache, name)
        total_added += a
        total_deleted += d
        shutil.rmtree(path, ignore_errors=True)

    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)

    values = {
        "UPTIME": uptime_string(BIRTH_DATE),
        "PERSONAL_REPOS": len(personal_repos),
        "OTHER_REPOS": len(other_repos),
        "PERSONAL_COMMITS": f"{personal_commits:,}",
        "OTHER_COMMITS": f"{other_commits:,}",
        "TOTAL_LOC": f"{total_added - total_deleted:,}",
        "LOC_ADDED": f"{total_added:,}",
        "LOC_DELETED": f"{total_deleted:,}",
    }

    with open("dark_mode.svg", "w") as f:
        f.write(render_svg(values, "dark", THEMES, ASCII_ART))
    with open("light_mode.svg", "w") as f:
        f.write(render_svg(values, "light", THEMES, ASCII_ART))


if __name__ == "__main__":
    main()