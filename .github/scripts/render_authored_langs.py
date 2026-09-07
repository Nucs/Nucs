#!/usr/bin/env python3
"""Language cards + stats from the user's OWN COMMITS across every repo.

Unlike render_langs.py (which sums GitHub Linguist byte-sizes of whole repos the user
owns, authorship-blind), this measures languages by the code the user actually authored:

  * metric   = NET lines (additions - deletions) in the user's own commits
  * identity = GitHub login (author=<login>); GitHub maps this via all the user's verified
               emails, so no email list is needed
  * scope    = repos the user OWNS (including forks and private) PLUS repos the user
               contributed to but does not own (org repos, upstreams)
  * branches = all branches; commits are deduped by commit hash globally, so a commit that
               lives in both a fork and its upstream (same sha) is counted once

State is committed so reruns are cheap and incremental:
  * stats/commits.json  - RAW per-commit data: {sha: {date, repo, langs:{lang:[add,del]}}}
  * stats/state.json    - run state incl. a DATE WATERMARK (max author-date seen) and the
                          set of repos already fully scanned
  * stats/README.md     - generated human-readable stats (method + tables + projects/era)
On each run only commits newer than the watermark are listed (GitHub `since=`), plus any
NEW repo is scanned in full; results merge into the raw file. Then the cards + doc + state
are rewritten. Commit stats/*, assets/*.svg after running.

Run LOCALLY (CI is intentionally disabled). Auth: GH_TOKEN/GITHUB_TOKEN if set, else
`gh auth token` (keyring). The token must read your private/org repos to count them.

The SVG is drawn by render_langs.build_svg (identical look); colors come from the palette below.
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
COUNT = int(os.environ.get("LANGS_COUNT", "5"))

RAW_PATH = os.environ.get("LANGS_RAW", "stats/commits.json")     # sha -> {date, repo, langs}
STATE_PATH = os.environ.get("LANGS_STATE", "stats/state.json")   # watermark + repos_seen
DOC_PATH = os.environ.get("LANGS_DOC", "stats/README.md")        # generated stats doc
LEGACY_LANGS = os.environ.get("LANGS_CACHE", "")                 # optional migration seed (sha->langs)
SINCE_BUFFER_DAYS = int(os.environ.get("LANGS_SINCE_BUFFER_DAYS", "7"))

# Historical "era" cards, drawn by the same authored / net-lines method, split by each
# commit's AUTHOR-date year (inclusive): (card title, output path, first year, last year).
ERAS = [
    ("Languages · 2012-2020", "assets/era-2012-2020.svg", 2012, 2020),
    ("Languages · 2021-2025", "assets/era-2021-2025.svg", 2021, 2025),
]
# Repos excluded FROM THE CARDS (owner/name, case-insensitive). Default excludes claude-dotdir:
# the user's private .claude dotfiles repo, whose committed JavaScript is bundled tooling, not
# authored code (~98% of the card's JS otherwise). They still appear in the raw data and the
# projects-by-era list (marked). Override/extend via LANGS_EXCLUDE_REPOS.
EXCLUDE_REPOS = {s.strip().lower() for s in os.environ.get("LANGS_EXCLUDE_REPOS", "Nucs/claude-dotdir").split(",") if s.strip()}
WORKERS = int(os.environ.get("LANGS_WORKERS", "6"))

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
    """All 'owner/name' the user owns (incl forks/private) or committed to. Exclusions are
    applied at card time, not here, so excluded repos still show in the raw data + projects list."""
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

    return repos


def authored_commits(repo, since=None):
    """{sha: author_date_iso} for commits in `repo` authored by LOGIN, across every branch.
    `since` (ISO) limits to commits after that time (incremental). Author date is free in
    the list response (no extra request)."""
    out = {}
    for br in rest_all("/repos/%s/branches" % repo, {"per_page": 100}):
        params = {"author": LOGIN, "sha": br["name"], "per_page": 100}
        if since:
            params["since"] = since
        for c in rest_all("/repos/%s/commits" % repo, params):
            out[c["sha"]] = c["commit"]["author"]["date"]
    return out


_LEGACY = None


def _legacy_langs():
    """Optional one-time migration seed: a plain {sha: langs} cache to avoid re-fetching."""
    global _LEGACY
    if _LEGACY is None:
        _LEGACY = {}
        if LEGACY_LANGS and os.path.exists(LEGACY_LANGS):
            try:
                _LEGACY = json.load(open(LEGACY_LANGS, encoding="utf-8"))
                print("  seeded %d langs from legacy cache %s" % (len(_LEGACY), LEGACY_LANGS), file=sys.stderr)
            except Exception:
                _LEGACY = {}
    return _LEGACY


def commit_langs(repo, sha):
    """{lang: [add, del]} for one commit, from its per-file stats."""
    leg = _legacy_langs()
    if sha in leg:
        return leg[sha]
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


def _net(raw, shas):
    """{lang: net_lines>0} aggregated over `shas` from the raw store."""
    net = {}
    for s in shas:
        for lang, (a, d) in raw[s]["langs"].items():
            net[lang] = net.get(lang, 0) + a - d
    return {k: v for k, v in net.items() if v > 0}


def render_card(raw, shas, title, out):
    """Aggregate NET lines per language over `shas` and write an SVG card to `out`."""
    net = _net(raw, shas)
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


def _save_raw(raw):
    os.makedirs(os.path.dirname(RAW_PATH) or ".", exist_ok=True)
    # sorted keys + compact => minimal, stable git diffs run-to-run
    json.dump(raw, open(RAW_PATH, "w", encoding="utf-8"), separators=(",", ":"), sort_keys=True)


DOC_ERAS = [("2012-2020", 2012, 2020), ("2021-2025", 2021, 2025), ("2026+", 2026, 3000)]


def write_doc(raw):
    def yr(s):
        return int(raw[s]["date"][:4])
    card = [s for s in raw if raw[s]["repo"].lower() not in EXCLUDE_REPOS]
    windows = [("All-time (Present card)", card),
               ("2012-2020", [s for s in card if 2012 <= yr(s) <= 2020]),
               ("2021-2025", [s for s in card if 2021 <= yr(s) <= 2025])]
    L = []
    L.append("# Language stats (from authored commits)\n\n")
    L.append("_Generated %s by `.github/scripts/render_authored_langs.py` from `%s`. Do not edit by hand._\n\n"
             % (datetime.date.today().isoformat(), RAW_PATH))
    L.append("## Method\n\n")
    L.append("- **Metric:** net lines (additions − deletions) in commits **authored by %s** "
             "(`author=%s`; GitHub maps all your verified emails).\n" % (LOGIN, LOGIN))
    L.append("- **Scope:** repos you own (incl. forks & private) **plus** repos you contributed to but "
             "don't own; **all branches**, deduped by commit hash (a commit in both a fork and its "
             "upstream counts once).\n")
    L.append("- **Excluded from cards:** %s (still shown in the projects list, marked).\n"
             % (", ".join(sorted(EXCLUDE_REPOS)) or "none"))
    L.append("- Vendored/generated/minified/binary paths skipped; docs/config markup skipped unless "
             "`LANGS_INCLUDE_MARKUP=1`.\n")
    L.append("- **Raw data:** `%s` (per-commit). **Run state / watermark:** `%s`. Reruns only fetch "
             "commits newer than the watermark.\n\n" % (RAW_PATH, STATE_PATH))
    for name, shas in windows:
        net = _net(raw, shas)
        tot = sum(net.values()) or 1
        L.append("## %s — %d commits, %s net lines\n\n" % (name, len(shas), "{:,}".format(sum(net.values()))))
        L.append("| Language | Net lines | Share |\n|---|--:|--:|\n")
        for lang, v in sorted(net.items(), key=lambda x: -x[1])[:COUNT]:
            L.append("| %s | %s | %.2f%% |\n" % (lang, "{:,}".format(v), v / tot * 100))
        L.append("\n")
    L.append("## Projects by era\n\n")
    L.append("_Deduped: each commit is counted once, under the repo it was first found in. "
             "Repos not owned by you and card-excluded repos are marked._\n\n")
    for nm, y0, y1 in DOC_ERAS:
        by = {}
        for s in raw:
            if y0 <= yr(s) <= y1:
                by[raw[s]["repo"]] = by.get(raw[s]["repo"], 0) + 1
        rows = sorted(by.items(), key=lambda x: -x[1])
        L.append("### %s — %d projects, %d commits\n\n" % (nm, len(rows), sum(by.values())))
        for repo, c in rows:
            tags = []
            if repo.lower() in EXCLUDE_REPOS:
                tags.append("excluded from cards")
            if not repo.lower().startswith(LOGIN.lower() + "/"):
                tags.append("not owned")
            suffix = "  _(%s)_" % ", ".join(tags) if tags else ""
            L.append("- %s (%d)%s\n" % (repo, c, suffix))
        L.append("\n")
    L.append("## Regenerate\n\n```sh\npython .github/scripts/render_authored_langs.py\n```\n")
    os.makedirs(os.path.dirname(DOC_PATH) or ".", exist_ok=True)
    open(DOC_PATH, "w", encoding="utf-8", newline="\n").write("".join(L))
    print("Wrote %s" % DOC_PATH, file=sys.stderr)


def main():
    raw = json.load(open(RAW_PATH, encoding="utf-8")) if os.path.exists(RAW_PATH) else {}
    state = json.load(open(STATE_PATH, encoding="utf-8")) if os.path.exists(STATE_PATH) else {}
    watermark = state.get("watermark")
    repos_seen = set(state.get("repos_seen", []))

    print("Enumerating repos for %s (raw has %d commits; watermark=%s) ..." % (LOGIN, len(raw), watermark), file=sys.stderr)
    repos = sorted(enumerate_repos())
    print("  %d repos" % len(repos), file=sys.stderr)

    since_param = None
    if watermark:
        try:
            dt = datetime.datetime.fromisoformat(watermark.replace("Z", "+00:00")) - datetime.timedelta(days=SINCE_BUFFER_DAYS)
            since_param = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            since_param = None

    # list authored commits: incremental (since watermark) for repos we've fully scanned,
    # full scan for repos seen for the first time.
    new_meta = {}  # sha -> (date, repo)
    for r in repos:
        since = since_param if (since_param and r in repos_seen) else None
        try:
            for sha, date in authored_commits(r, since).items():
                if sha not in raw and sha not in new_meta:
                    new_meta[sha] = (date, r)
        except Exception as e:
            print("  skip %s (%s)" % (r, e), file=sys.stderr)
        repos_seen.add(r)
    print("  %d new commits to fetch" % len(new_meta), file=sys.stderr)

    def fetch(item):
        sha, (date, repo) = item
        try:
            return sha, date, repo, commit_langs(repo, sha)
        except Exception as e:  # transient -> None so it is NOT stored and retries next run
            print("  detail failed %s@%s (%s)" % (sha[:8], repo, e), file=sys.stderr)
            return sha, None, None, None

    items = list(new_meta.items())
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for sha, date, repo, langs in ex.map(fetch, items):
            done += 1
            if langs is not None:
                raw[sha] = {"date": date, "repo": repo, "langs": langs}
            if done % 200 == 0:
                print("    fetched %d/%d" % (done, len(items)), file=sys.stderr)
                _save_raw(raw)
    _save_raw(raw)

    if not raw:
        print("No authored data; nothing to render.", file=sys.stderr)
        return 1

    def yr(s):
        return int(raw[s]["date"][:4])
    card_shas = [s for s in raw if raw[s]["repo"].lower() not in EXCLUDE_REPOS]
    render_card(raw, card_shas, TITLE, OUT)  # all-time "Present" card
    for title, out, y0, y1 in ERAS:
        subset = [s for s in card_shas if y0 <= yr(s) <= y1]
        print("  era %s: %d commits" % (title, len(subset)), file=sys.stderr)
        render_card(raw, subset, title, out)

    write_doc(raw)
    watermark = max((raw[s]["date"] for s in raw), default=watermark)
    state = {
        "login": LOGIN,
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "watermark": watermark,          # next run lists commits since this (minus buffer)
        "since_buffer_days": SINCE_BUFFER_DAYS,
        "commit_count": len(raw),
        "excluded_from_cards": sorted(EXCLUDE_REPOS),
        "repos_seen": sorted(repos_seen),
    }
    os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
    json.dump(state, open(STATE_PATH, "w", encoding="utf-8"), indent=2)
    print("Done: %d commits, watermark=%s, %d repos seen" % (len(raw), watermark, len(repos_seen)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
