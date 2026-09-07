# Language stats (from authored commits)

_Generated 2026-09-07 by `.github/scripts/render_authored_langs.py` from `stats/commits.json`. Do not edit by hand._

## Method

- **Metric:** net lines (additions − deletions) in commits **authored by Nucs** (`author=Nucs`; GitHub maps all your verified emails).
- **Scope:** repos you own (incl. forks & private) **plus** repos you contributed to but don't own; **all branches**, deduped by commit hash (a commit in both a fork and its upstream counts once).
- **Excluded from cards:** nucs/claude-dotdir (still shown in the projects list, marked).
- Vendored/generated/minified/binary paths skipped; docs/config markup skipped unless `LANGS_INCLUDE_MARKUP=1`.
- **Raw data:** `stats/commits.json` (per-commit). **Run state / watermark:** `stats/state.json`. Reruns only fetch commits newer than the watermark.

## All-time (Present card) — 7526 commits, 1,835,712 net lines

| Language | Net lines | Share |
|---|--:|--:|
| C# | 1,144,425 | 62.34% |
| Python | 177,688 | 9.68% |
| TypeScript | 112,408 | 6.12% |
| C++ | 107,875 | 5.88% |
| C | 101,430 | 5.53% |

## 2012-2020 — 1375 commits, 1,629,495 net lines

| Language | Net lines | Share |
|---|--:|--:|
| C# | 1,480,711 | 90.87% |
| AutoIt | 81,627 | 5.01% |
| C | 29,745 | 1.83% |
| CSS | 20,415 | 1.25% |
| C++ | 11,250 | 0.69% |

## 2021-2025 — 2568 commits, 169,329 net lines

| Language | Net lines | Share |
|---|--:|--:|
| C# | 61,250 | 36.17% |
| Python | 60,712 | 35.85% |
| C | 41,981 | 24.79% |
| HTML | 2,900 | 1.71% |
| Shell | 1,054 | 0.62% |

## Projects by era

_Deduped: each commit is counted once, under the repo it was first found in. Repos not owned by you and card-excluded repos are marked._

### 2012-2020 — 28 projects, 1375 commits

- Nucs/NumSharp-dev (545)
- SciSharp/TensorFlow.NET (143)  _(not owned)_
- SciSharp/CodeMinion (104)  _(not owned)_
- Nucs/nlib (81)
- Nucs/neuron (77)
- Nucs/FinanceSharp (75)
- Nucs/JsonSettings (61)
- SciSharp/Gym.NET (41)  _(not owned)_
- Nucs/BtcPoclbmWrapper (32)
- Nucs/Chaining (29)
- Nucs/cryptocurrency-ticks-data (26)
- Nucs/YoutubeExtractor-Improved (24)
- Nucs/Autocad-Utilities (23)
- Nucs/nucs.Automation (21)
- ivanslifer12/Matam_3 (21)  _(not owned)_
- Nucs/Regen (18)
- Nucs/nucs.Filesystem (15)
- Nucs/FontRegister (9)
- Nucs/machinelearning (7)
- Nucs/Alda (4)
- Nucs/nlib.Paypal-IPN (4)
- Nucs/nucs.Emailing (4)
- Nucs/IQFeed.CSharpApiClient-Fork (3)
- Nucs/elecstudy-org (3)
- Nucs/mybot-nucs (2)
- Nucs/Dapper.SimpleCRUD (1)
- Nucs/TensorFlow.NET (1)
- Nucs/TensorFlowNetMultithreading (1)

### 2021-2025 — 28 projects, 2606 commits

- Nucs/ML.NET.Api (1080)
- Nucs/gits-temp (771)
- Nucs/FontRegister (135)
- Nucs/Nucs.Essentials (120)
- Nucs/scheduler (86)
- Nucs/portainer_templates (82)
- Nucs/JsonSettings (67)
- Nucs/claude-dotdir (38)  _(excluded from cards)_
- Nucs/python-scripts (30)
- Nucs/NumSharp-dev (29)
- Nucs/TraderLab (25)
- Nucs/claude-code-python-sdk-unofficial-docs (25)
- Nucs/Nucs (18)
- Nucs/CarFinder (14)
- SciSharp/Gym.NET (14)  _(not owned)_
- Nucs/IQFeed.CSharpApiClient-Fork (11)
- Nucs/SlickDirectory (11)
- Nucs/log4net-loggly-async (10)
- Nucs/utf8clip (9)
- Nucs/DiscordBackup (8)
- Nucs/GameOfLifePingPong (7)
- Nucs/ClaudeCodeProxy (5)
- Nucs/loggly-net (3)
- Nucs/GPT-Prompts-Library (2)
- Nucs/Packer (2)
- Nucs/ryzen-7000-series-proxmox (2)
- Nucs/copypasta (1)
- isc30/ryzen-gpu-passthrough-proxmox (1)  _(not owned)_

### 2026+ — 20 projects, 3836 commits

- SciSharp/NumSharp (1820)  _(not owned)_
- Nucs/Agentmaster (833)
- Nucs/TraderLab (326)
- Nucs/claude-dotdir (253)  _(excluded from cards)_
- Nucs/OptunaSharp (167)
- Nucs/JsonSettings (114)
- Nucs/OssAnalytics (66)
- Nucs/RdpDoorway (50)
- Nucs/DataBeam (46)
- Nucs/Nucs (38)
- Nucs/Obsidian (35)
- Nucs/chairflow (22)
- Nucs/NumSharp-dev (21)
- Nucs/sidebedlight (16)
- Nucs/ROCCATSwarmApi (11)
- Nucs/topmost2 (6)
- Nucs/altshift2 (4)
- Nucs/FinanceSharp (3)
- Nucs/FontRegister (3)
- Nucs/OpenDictionarius (2)

## Regenerate

```sh
python .github/scripts/render_authored_langs.py
```
