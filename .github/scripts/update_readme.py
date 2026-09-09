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


def build_stat_lines(values):
    """Returns the right-hand column as plain text lines (SVG coloring is
    applied separately in render_svg)."""
    return [
        "kkura@git",
        "----------",
        f"OS:      Windows 11, iOS, Ubuntu",
        f"Uptime:  {values['UPTIME']}",
        f"Kernel:  Data Quality / IT Support",
        f"IDE:     VSCode",
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


# ---- SVG rendering ----------------------------------------------------------
THEMES = {
    "dark": {
        "bg": "#0d1117",
        "border": "#30363d",
        "header": "#79c0ff",
        "dash": "#8b949e",
        "section": "#d2a8ff",
        "label": "#ff7b72",
        "value": "#c9d1d9",
        "art": "#58a6ff",
    },
    "light": {
        "bg": "#ffffff",
        "border": "#d0d7de",
        "header": "#0969da",
        "dash": "#57606a",
        "section": "#8250df",
        "label": "#cf222e",
        "value": "#24292f",
        "art": "#0969da",
    },
}

FONT_SIZE = 14
LINE_HEIGHT = 20
CHAR_W = 8.4
PAD = 24
ART_X = PAD
STATS_X = PAD + max(len(l) for l in ASCII_ART) * CHAR_W + 40


def classify_line(text, colors):
    """Returns a list of (substring, color) tspans for one stats line."""
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

    # ASCII art column
    art_y = PAD + FONT_SIZE
    parts.append(f'<text x="{ART_X}" y="{art_y}" fill="{colors["art"]}" xml:space="preserve">')
    for i, line in enumerate(ASCII_ART):
        dy = 0 if i == 0 else LINE_HEIGHT
        parts.append(f'<tspan x="{ART_X}" dy="{dy}">{escape(line)}</tspan>')
    parts.append("</text>")

    # Stats column
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
        f.write(render_svg(values, "dark"))
    with open("light_mode.svg", "w") as f:
        f.write(render_svg(values, "light"))


if __name__ == "__main__":
    main()
