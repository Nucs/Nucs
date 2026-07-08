#!/usr/bin/env python3
"""Render the "Languages - Present" card (assets/langs-live.svg) from the GitHub API.

Why this exists
---------------
The README used to embed a *live* image from github-readme-stats.vercel.app. That is a
shared community service that regularly gets paused / rate-limited by Vercel, so GitHub's
camo proxy renders "Error Fetching Resource" whenever it is down.

This script reproduces github-readme-stats' ``top-langs`` **compact** layout exactly, but
computes the numbers ourselves from the GitHub GraphQL API and writes a *static* SVG that
is committed to the repo. GitHub then serves it directly -- so the card can never fail to
load at view time, and there is no third-party dependency at build time either.

It is run both locally (to seed the file) and from CI (.github/workflows/refresh-langs.yml).
It shells out to ``gh api graphql``, which automatically uses GH_TOKEN / GITHUB_TOKEN.

Configuration (all optional, via env vars):
    LANGS_LOGIN    GitHub user            (default: nucs)
    LANGS_EXCLUDE  comma-separated repos  (default: ML.NET.Api)
    LANGS_TITLE    card title             (default: "Languages - Present")
    LANGS_OUT      output path            (default: assets/langs-live.svg)
    LANGS_COUNT    number of languages    (default: 5)
"""
import datetime
import html
import json
import os
import subprocess
import sys

LOGIN = os.environ.get("LANGS_LOGIN", "nucs")
EXCLUDE = {s.strip() for s in os.environ.get("LANGS_EXCLUDE", "ML.NET.Api").split(",") if s.strip()}
TITLE = os.environ.get("LANGS_TITLE", "Languages · Present")  # · = middle dot
OUT = os.environ.get("LANGS_OUT", "assets/langs-live.svg")
LANGS_COUNT = int(os.environ.get("LANGS_COUNT", "5"))

WIDTH = 300
OFFSET_WIDTH = WIDTH - 50  # github-readme-stats: paddingRight = 50 -> bar width 250

# Same shape github-readme-stats uses: owner-affiliated, non-fork repos, first 100.
QUERY = """
query($login:String!){
  user(login:$login){
    repositories(ownerAffiliations:OWNER, isFork:false, first:100){
      nodes{
        name
        languages(first:20, orderBy:{field:SIZE, direction:DESC}){
          edges{ size node{ name color } }
        }
      }
    }
  }
}
"""


def fetch():
    proc = subprocess.run(
        ["gh", "api", "graphql", "-f", "login=%s" % LOGIN, "-f", "query=%s" % QUERY],
        check=True, capture_output=True, text=True,
    )
    return json.loads(proc.stdout)


def build_svg(top, colors, total):
    # --- stacked compact progress bar (github-readme-stats algorithm) ---
    # each segment's drawn width is its % of the 250px bar; segments < 10px get +10px so
    # they stay visible, and the x-offset accumulates the *raw* widths (overlap is masked).
    progress = []
    offset = 0.0
    for name, sz in top:
        wpx = round(sz / total * OFFSET_WIDTH, 2)
        draw = round(wpx + 10, 2) if wpx < 10 else wpx
        progress.append(
            '        <rect\n'
            '          mask="url(#rect-mask)"\n'
            '          data-testid="lang-progress"\n'
            '          x="%s"\n'
            '          y="0"\n'
            '          width="%s"\n'
            '          height="8"\n'
            '          fill="%s"\n'
            '        />' % (round(offset, 2), draw, colors[name]))
        offset += wpx

    def node(name, sz, delay):
        pct = round(sz / total * 100, 2)
        return (
            '    <g class="stagger" style="animation-delay: %dms">\n'
            '      <circle cx="5" cy="6" r="5" fill="%s" />\n'
            '      <text data-testid="lang-name" x="15" y="10" class=\'lang-name\'>\n'
            '        %s %.2f%%\n'
            '      </text>\n'
            '    </g>' % (delay, colors[name], html.escape(name), pct))

    # two columns: first ceil(n/2), remainder in the second
    half = (len(top) + 1) // 2
    columns = (top[:half], top[half:])

    def column(items):
        return "".join(
            '<g transform="translate(0, %d)">%s\n  </g>' % (i * 25, node(name, sz, 450 + i * 150))
            for i, (name, sz) in enumerate(items))

    col1, col2 = (column(c) for c in columns)
    title_xml = html.escape(TITLE).replace("·", "&#183;")

    svg = '''
      <svg
        width="300"
        height="165"
        viewBox="0 0 300 165"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-labelledby="descId"
      >
        <title id="titleId"></title>
        <desc id="descId"></desc>
        <style>
          .header {
            font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif;
            fill: #6366F1;
            animation: fadeInAnimation 0.8s ease-in-out forwards;
          }
          @supports(-moz-appearance: auto) {
            /* Selector detects Firefox */
            .header { font-size: 15.5px; }
          }

    @keyframes slideInAnimation {
      from {
        width: 0;
      }
      to {
        width: calc(100%-100px);
      }
    }
    @keyframes growWidthAnimation {
      from {
        width: 0;
      }
      to {
        width: 100%;
      }
    }
    .stat {
      font: 600 14px 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif; fill: #C9D1D9;
    }
    @supports(-moz-appearance: auto) {
      /* Selector detects Firefox */
      .stat { font-size:12px; }
    }
    .bold { font-weight: 700 }
    .lang-name {
      font: 400 11px "Segoe UI", Ubuntu, Sans-Serif;
      fill: #C9D1D9;
    }
    .stagger {
      opacity: 0;
      animation: fadeInAnimation 0.3s ease-in-out forwards;
    }
    #rect-mask rect{
      animation: slideInAnimation 1s ease-in-out forwards;
    }
    .lang-progress{
      animation: growWidthAnimation 0.6s ease-in-out forwards;
    }



      /* Animations */
      @keyframes scaleInAnimation {
        from {
          transform: translate(-5px, 5px) scale(0);
        }
        to {
          transform: translate(-5px, 5px) scale(1);
        }
      }
      @keyframes fadeInAnimation {
        from {
          opacity: 0;
        }
        to {
          opacity: 1;
        }
      }


        </style>



        <rect
          data-testid="card-bg"
          x="0.5"
          y="0.5"
          rx="4.5"
          height="99%"
          stroke="#e4e2e2"
          width="299"
          fill="#0D1117"
          stroke-opacity="0"
        />


      <g
        data-testid="card-title"
        transform="translate(25, 35)"
      >
        <g transform="translate(0, 0)">
      <text
        x="0"
        y="0"
        class="header"
        data-testid="header"
      >__TITLE__</text>
    </g>
      </g>


        <g
          data-testid="main-card-body"
          transform="translate(0, 55)"
        >

    <svg data-testid="lang-items" x="25">


      <mask id="rect-mask">
          <rect x="0" y="0" width="250" height="8" fill="white" rx="5"/>
        </mask>

__PROGRESS__


    <g transform="translate(0, 25)">
      <g transform="translate(0, 0)">__COL1__</g><g transform="translate(150, 0)">__COL2__</g>
    </g>

    </svg>

        </g>
      </svg>
    '''

    svg = (svg.replace("__TITLE__", title_xml)
              .replace("__PROGRESS__", "\n".join(progress))
              .replace("__COL1__", col1)
              .replace("__COL2__", col2))

    # Stamp the refresh date just before the closing </svg>. This keeps the file changing
    # on each (monthly) refresh so the CI staleness clock resets even when the numbers are
    # unchanged -- and documents when the card was last regenerated.
    stamp = "  <!-- refreshed %s from the GitHub GraphQL API -->\n      " % datetime.date.today().isoformat()
    idx = svg.rfind("</svg>")
    svg = svg[:idx] + stamp + svg[idx:]
    return svg


def main():
    data = fetch()
    nodes = data["data"]["user"]["repositories"]["nodes"]
    sizes, colors = {}, {}
    for repo in nodes:
        if repo["name"] in EXCLUDE:
            continue
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            sizes[name] = sizes.get(name, 0) + edge["size"]
            colors.setdefault(name, edge["node"]["color"] or "#858585")

    if not sizes:
        print("No language data returned; leaving the existing card untouched.", file=sys.stderr)
        return 1

    total = sum(sizes.values())
    top = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)[:LANGS_COUNT]

    svg = build_svg(top, colors, total)
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)

    print("Wrote %s (%d bytes)" % (OUT, len(svg.encode("utf-8"))))
    for name, sz in top:
        print("  %-14s %6.2f%%" % (name, sz / total * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
