#!/usr/bin/env python3
"""Render the "Languages - Present" card from the user's OWN COMMITS across every repo.

Unlike render_langs.py (which sums GitHub Linguist byte-sizes of whole repos the user
owns, authorship-blind), this measures languages by the code the user actually authored:

  * metric   = NET lines (additions - deletions) in the user's own commits
  * identity = GitHub login (author=<login>); GitHub maps this via all the user's verified
               emails, so no email list is needed
  * scope    = repos the user OWNS (including forks and private) PLUS repos the user
               contributed to but does not own (org repos, upstreams)
  * branches = all branches; commits are deduped by commit hash globally, so a commit that
               lives in both a fork and its upstream (same sha) is counted once

Per-commit file stats are cached in assets/.langs-cache.json (sha -> {lang: [add, del]}),
so the first run is expensive but every later run only fetches commits it has not seen.

Run this LOCALLY only (CI is intentionally disabled - no refresh workflow). It authenticates
with `gh auth token` (your keyring login), or GH_TOKEN/GITHUB_TOKEN if set; the token must be
able to read your private/org repos for those to be counted. Regenerate and commit the card
(assets/langs-live.svg) whenever you want it refreshed.

The SVG is drawn by render_langs.build_svg (identical look); colors come from the canonical
linguist palette below.
"""
import datetime
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import render_langs  # reuse build_svg (same card layout) and its COLOR_OVERRIDES

LOGIN = os.environ.get("LANGS_LOGIN", "Nucs")
OUT = os.environ.get("LANGS_OUT", "assets/langs-live.svg")
TITLE = os.environ.get("LANGS_TITLE", "Languages · Present")  # all-time card header
CACHE_PATH = os.environ.get("LANGS_CACHE", "assets/.langs-cache.json")
COUNT = int(os.environ.get("LANGS_COUNT", "5"))
DATES_CACHE = os.environ.get("LANGS_DATES", "assets/.langs-dates.json")
# Historical "era" cards, drawn by the same authored / net-lines method, split by each
# commit's AUTHOR-date year (inclusive): (card title, output path, first year, last year).
ERAS = [
    ("Languages · 2012-2020", "assets/era-2012-2020.svg", 2012, 2020),
    ("Languages · 2021-2025", "assets/era-2021-2025.svg", 2021, 2025),
]
# Repos to skip entirely (owner/name, case-insensitive). Default excludes claude-dotdir:
# the user's private .claude dotfiles repo, whose committed JavaScript is bundled tooling,
# not authored code (~98% of the card's JS otherwise). Override/extend via LANGS_EXCLUDE_REPOS.
EXCLUDE_REPOS = {s.strip().lower() for s in os.environ.get("LANGS_EXCLUDE_REPOS", "Nucs/claude-dotdir").split(",") if s.strip()}
WORKERS = int(os.environ.get("LANGS_WORKERS", "8"))

API = "https://api.github.com"


def _token():
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


TOKEN = _token()
HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Accept": "application/vnd.github+json",
    "User-Agent": "nucs-langs-card",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _req(url):
    """GET a REST url -> (json, link_header). Retries rate-limit / 5xx / dropped connections;
    raises if it ultimately fails. Returns (None, "") only for genuinely-absent resources
    (404/409/410/451) so callers can distinguish 'no data' from 'fetch failed'."""
    last = None
    for attempt in range(7):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                return (json.loads(body) if body else None), r.headers.get("Link", "")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):  # primary / secondary rate limit
                reset = e.headers.get("X-RateLimit-Reset")
                wait = max(2, int(reset) - int(time.time()) + 2) if reset else 2 ** attempt
                print("  rate-limited; sleeping %ss" % min(wait, 300), file=sys.stderr)
                time.sleep(min(wait, 300)); last = e; continue
            if e.code in (500, 502, 503, 504):
                time.sleep(min(2 ** attempt, 30)); last = e; continue
            if e.code in (404, 409, 410, 451):  # absent / blocked / DMCA -> genuinely no data
                return None, ""
            raise
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError, OSError) as e:
            time.sleep(min(2 ** attempt + 1, 30)); last = e; continue
    raise RuntimeError("request failed after retries: %s (%s)" % (url, last))


def rest_all(path, params):
    """Yield items across all pages of a REST list endpoint."""
    url = API + path + "?" + urllib.parse.urlencode(params)
    while url:
        data, link = _req(url)
        if not data:
            return
        for it in data:
            yield it
        url = ""
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part[part.find("<") + 1:part.find(">")]


def graphql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    for attempt in range(6):
        req = urllib.request.Request(API + "/graphql", data=body, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 500, 502, 503, 504):
                time.sleep(min(2 ** attempt, 30))
                continue
            raise
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError, OSError):
            time.sleep(min(2 ** attempt + 1, 30))
            continue
    raise RuntimeError("graphql failed")


def enumerate_repos():
    """Return a set of 'owner/name' the user owns (incl forks/private) or committed to."""
    repos, created = set(), None
    after = None
    while True:
        q = """
        query($login:String!,$after:String){user(login:$login){
          createdAt
          repositories(ownerAffiliations:OWNER,first:100,after:$after){
            pageInfo{hasNextPage endCursor}
            nodes{nameWithOwner isEmpty}}}}"""
        d = graphql(q, {"login": LOGIN, "after": after})["data"]["user"]
        created = created or d["createdAt"]
        page = d["repositories"]
        for n in page["nodes"]:
            if not n["isEmpty"]:
                repos.add(n["nameWithOwner"])
        if page["pageInfo"]["hasNextPage"]:
            after = page["pageInfo"]["endCursor"]
        else:
            break

    # Repos contributed to but not owned: contributionsCollection per year (repositoriesContributedTo
    # under-reports), from account creation to now.
    year0 = int(created[:4])
    for y in range(year0, datetime.date.today().year + 1):
        q = """
        query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){
          contributionsCollection(from:$from,to:$to){
            commitContributionsByRepository(maxRepositories:100){repository{nameWithOwner}}}}}"""
        v = {"login": LOGIN, "from": "%d-01-01T00:00:00Z" % y, "to": "%d-12-31T23:59:59Z" % y}
        col = graphql(q, v)["data"]["user"]["contributionsCollection"]["commitContributionsByRepository"]
        for c in col:
            repos.add(c["repository"]["nameWithOwner"])

    return {r for r in repos if r.lower() not in EXCLUDE_REPOS}


def authored_commits(repo):
    """{sha: author_date_iso} for commits in `repo` authored by LOGIN, across every branch.
    The author date comes free in the commit-list response (no extra request)."""
    out = {}
    for br in rest_all("/repos/%s/branches" % repo, {"per_page": 100}):
        name = br["name"]
        for c in rest_all("/repos/%s/commits" % repo, {"author": LOGIN, "sha": name, "per_page": 100}):
            out[c["sha"]] = c["commit"]["author"]["date"]
    return out


def authored_shas(repo):
    """Just the deduped sha set (kept for callers that don't need dates)."""
    return set(authored_commits(repo))


def commit_langs(repo, sha):
    """{lang: [add, del]} for one commit, from its per-file stats (cached upstream)."""
    data, _ = _req("%s/repos/%s/commits/%s" % (API, repo, sha))
    out = {}
    if not data:
        return out
    for f in data.get("files", []):
        lang = classify(f.get("filename", ""))
        if not lang:
            continue
        a, d = f.get("additions", 0), f.get("deletions", 0)
        cur = out.setdefault(lang, [0, 0])
        cur[0] += a
        cur[1] += d
    return out


# ---- filename -> language (curated linguist subset) + vendored/generated skips ----
EXT2LANG = {
    ".cs": "C#", ".csx": "C#", ".py": "Python", ".pyi": "Python", ".pyx": "Python",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++", ".hh": "C++", ".hxx": "C++", ".ino": "C++",
    ".c": "C", ".h": "C", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".html": "HTML", ".htm": "HTML", ".cshtml": "HTML", ".razor": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sass": "Sass", ".less": "Less",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell", ".psm1": "PowerShell", ".psd1": "PowerShell",
    ".bat": "Batchfile", ".cmd": "Batchfile", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".m": "Objective-C", ".mm": "Objective-C++",
    ".scala": "Scala", ".dart": "Dart", ".lua": "Lua", ".r": "R", ".jl": "Julia", ".hs": "Haskell",
    ".sql": "SQL", ".fs": "F#", ".fsx": "F#", ".vb": "Visual Basic .NET", ".pl": "Perl", ".pm": "Perl",
    ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang", ".clj": "Clojure", ".groovy": "Groovy",
    ".au3": "AutoIt", ".tcl": "Tcl", ".hlsl": "HLSL", ".glsl": "GLSL", ".sol": "Solidity",
    ".vue": "Vue", ".svelte": "Svelte", ".dockerfile": "Dockerfile", ".cmake": "CMake",
    ".ipynb": "Jupyter Notebook", ".md": "Markdown", ".markdown": "Markdown", ".yml": "YAML", ".yaml": "YAML",
    ".json": "JSON", ".xml": "XML", ".toml": "TOML", ".proto": "Protocol Buffer",
}
BASENAME2LANG = {"dockerfile": "Dockerfile", "makefile": "Makefile", "cmakelists.txt": "CMake"}
# Non-code / markup we do not want to weight as "languages I write". Toggle via env if desired.
NON_CODE = {"Markdown", "YAML", "JSON", "XML", "TOML"} if os.environ.get("LANGS_INCLUDE_MARKUP") != "1" else set()
SKIP_SUBSTR = (
    "/node_modules/", "/bower_components/", "/vendor/", "/vendored/", "/third_party/", "/thirdparty/",
    "/external/", "/externals/", "/dist/", "/build/", "/bin/", "/obj/", "/packages/", "/.venv/", "/venv/",
    "/refs/", "/deps/", "/.git/", "/generated/", "/__pycache__/", "/site-packages/", "/wwwroot/lib/",
)
SKIP_SUFFIX = (".min.js", ".min.css", ".map", ".g.cs", ".designer.cs", ".g.i.cs", "-lock.json",
               ".lock", ".pb.go", "_pb2.py")


def classify(path):
    p = path.lower()
    if any(s in "/" + p for s in SKIP_SUBSTR):
        return None
    if any(p.endswith(s) for s in SKIP_SUFFIX):
        return None
    base = p.rsplit("/", 1)[-1]
    if base in BASENAME2LANG:
        lang = BASENAME2LANG[base]
    else:
        dot = base.rfind(".")
        if dot < 0:
            return None
        lang = EXT2LANG.get(base[dot:])
    if not lang or lang in NON_CODE:
        return None
    return lang


LANG_COLORS = dict(render_langs.COLOR_OVERRIDES)
LANG_COLORS.update({
    "SCSS": "#c6538c", "Sass": "#a53b70", "Less": "#1d365d", "Kotlin": "#A97BFF", "Ruby": "#701516",
    "PHP": "#4F5D95", "Swift": "#F05138", "Objective-C": "#438eff", "Objective-C++": "#6866fb",
    "Scala": "#c22d40", "Dart": "#00B4AB", "Lua": "#000080", "R": "#198CE7", "Julia": "#a270ba",
    "Haskell": "#5e5086", "SQL": "#e38c00", "F#": "#b845fc", "Visual Basic .NET": "#945db7",
    "Perl": "#0298c3", "Elixir": "#6e4a7e", "Erlang": "#B83998", "Clojure": "#db5855", "Groovy": "#4298b8",
    "AutoIt": "#1C3552", "Tcl": "#e4cc98", "HLSL": "#aace60", "GLSL": "#5686a5", "Solidity": "#AA6746",
    "Vue": "#41b883", "Svelte": "#ff3e00", "Makefile": "#427819", "Protocol Buffer": "#7fa2c9",
    "Markdown": "#083fa1", "YAML": "#cb171e", "JSON": "#292929", "XML": "#0060ac", "TOML": "#9c4221",
})


def render_card(cache, shas, title, out):
    """Aggregate NET lines per language over `shas` and write an SVG card to `out`."""
    net = {}
    for s in shas:
        for lang, (a, d) in cache.get(s, {}).items():
            net[lang] = net.get(lang, 0) + a - d
    net = {k: v for k, v in net.items() if v > 0}
    if not net:
        print("  no authored data for %s; leaving it unchanged" % out, file=sys.stderr)
        return
    total = sum(net.values())
    top = sorted(net.items(), key=lambda kv: kv[1], reverse=True)[:COUNT]
    colors = {n: LANG_COLORS.get(n, "#858585") for n, _ in top}
    render_langs.TITLE = title  # build_svg reads render_langs.TITLE
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_langs.build_svg(top, colors, total))
    print("Wrote %s: %s" % (out, ", ".join("%s %.2f%%" % (n, v / total * 100) for n, v in top)), file=sys.stderr)


def main():
    print("Enumerating repos for %s ..." % LOGIN, file=sys.stderr)
    repos = sorted(enumerate_repos())
    print("  %d repos" % len(repos), file=sys.stderr)

    # cache: sha -> {lang: [add, del]}
    cache = {}
    if os.path.exists(CACHE_PATH):
        cache = json.load(open(CACHE_PATH, encoding="utf-8"))

    # collect every authored sha (with its author-date) across all repos/branches, deduped
    sha_repo, sha_date = {}, {}
    for r in repos:
        try:
            for s, dt in authored_commits(r).items():
                sha_repo.setdefault(s, r)   # first repo that has this sha
                sha_date.setdefault(s, dt)
        except Exception as e:
            print("  skip %s (%s)" % (r, e), file=sys.stderr)
    print("  %d unique authored commits" % len(sha_repo), file=sys.stderr)
    os.makedirs(os.path.dirname(DATES_CACHE) or ".", exist_ok=True)
    json.dump(sha_date, open(DATES_CACHE, "w", encoding="utf-8"))

    missing = [(s, r) for s, r in sha_repo.items() if s not in cache]
    print("  %d new commits to fetch (%d cached)" % (len(missing), len(sha_repo) - len(missing)), file=sys.stderr)

    def fetch(item):
        s, r = item
        try:
            return s, commit_langs(r, s)
        except Exception as e:  # transient failure -> None so it is NOT cached and retries next run
            print("  detail failed %s@%s (%s)" % (s[:8], r, e), file=sys.stderr)
            return s, None

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for s, langs in ex.map(fetch, missing):
            done += 1
            if langs is not None:
                cache[s] = langs
            if done % 200 == 0:
                print("    fetched %d/%d" % (done, len(missing)), file=sys.stderr)
                json.dump(cache, open(CACHE_PATH, "w", encoding="utf-8"))
    json.dump(cache, open(CACHE_PATH, "w", encoding="utf-8"))

    render_card(cache, sha_repo.keys(), TITLE, OUT)  # all-time "Present" card
    for title, out, y0, y1 in ERAS:      # historical era cards, split by author-date year
        subset = [s for s in sha_repo if y0 <= int(sha_date.get(s, "9999")[:4]) <= y1]
        print("  era %s: %d commits" % (title, len(subset)), file=sys.stderr)
        render_card(cache, subset, title, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
