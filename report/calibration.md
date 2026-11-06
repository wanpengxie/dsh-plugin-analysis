# Calibration top-30 report

- Scope: 30 fixed commits from lists/calibration-top30.csv
- Static analysis only; no plugin code executed
- Valid: 14; failed after one rewrite: 16
- End-to-end wall time: 41.9 min; amortized 83.7 s/repo with 10-way concurrency
- Per-repository stage timing was not reliably captured; see recommendation below.

| Rank | Repository | Status | Topic | Risk | Quality | Units |
|---:|---|---|---|---|---|---:|
| 1 | Ebony-Vinyl/dsh-our-free-model | failed | — | — | — | 0 |
| 2 | alchaincyf/nuwa-skill | failed | — | — | — | 0 |
| 3 | alchaincyf/huashu-design | failed | — | — | — | 0 |
| 4 | HunYiSage/dsh-purge | failed | — | — | — | 0 |
| 5 | dsh-market/dsh-market | failed | — | — | — | 0 |
| 6 | zhu1090093659/dsh-web | failed | — | — | — | 0 |
| 7 | superdesigndev/treg | failed | — | — | — | 0 |
| 8 | ccch1mneyyy/dsh-TUI | failed | — | — | — | 0 |
| 9 | yjh051108/dsh-routing-suite | failed | — | — | — | 0 |
| 10 | MeteorNOX/DeepSeek-Balance-Whale-Widget | failed | — | — | — | 0 |
| 11 | QingYunA/answer-me-with-html | success | design-output | none | A | 105 |
| 12 | elysia395/dsh-wallpaper-engine | failed | — | — | — | 0 |
| 13 | T-Auto/dsh-ops | failed | — | — | — | 0 |
| 14 | omdsh-dev/DSH-better-sidebar | failed | — | — | — | 0 |
| 15 | liustack/modlens | failed | — | — | — | 0 |
| 16 | kingcharleslzy-ai/dsh-purge | success | jailbreak | medium | A | 85 |
| 17 | bowenliang123/dsh-context | success | context-memory | none | A | 53 |
| 18 | ranxianglei/billion-context | success | context-memory | medium | S | 208 |
| 19 | Minglink/dsh-infinite-gen-5 | success | dev-tools | medium | B | 54 |
| 20 | xmanrui/dsh-im | success | im-integration | none | A | 175 |
| 21 | mmparko/dsh-purge | success | jailbreak | medium | B | 131 |
| 22 | shaobeichen/dsh-pocket | success | remote-mobile | none | A | 74 |
| 23 | NanmiCoder/dsh-agent-teams | failed | — | — | — | 0 |
| 24 | Jesseovo/last30days-skill-cn | success | research-search | medium | A | 46 |
| 25 | liguobao/ds-harness-remote | success | remote-mobile | none | A | 176 |
| 26 | kenryu42/cc-safety-net | success | dev-tools | none | A | 52 |
| 27 | sixtysevenlf/dsh-blender-plugin | failed | — | — | — | 0 |
| 28 | hyhmrright/brooks-lint | success | dev-tools | none | A | 143 |
| 29 | GanyuanRan/Aegis | success | dev-tools | none | A | 84 |
| 30 | vshulcz/deja-vu | success | context-memory | none | A | 114 |

## Failed repositories

- Ebony-Vinyl/dsh-our-free-model: missing card: /data/dsh-plugin-analysis/results/cards/Ebony-Vinyl__dsh-our-free-model.json
- alchaincyf/nuwa-skill: card length 147: alchaincyf__nuwa-skill#card-zh; card length 306: alchaincyf__nuwa-skill#card-en; feature length 37: alchaincyf__nuwa-skill#feature-diagnose
- alchaincyf/huashu-design: card length 564: alchaincyf__huashu-design#card-en; feature length 39: alchaincyf__huashu-design#feature-f1; feature length 31: alchaincyf__huashu-design#feature-f2; feature length 27: alchaincyf__huashu-design#feature-f3
- HunYiSage/dsh-purge: api key absent from facts.config: FOFA_KEY; api key absent from facts.config: REDTEAM_VPS_KEY; card length 461: HunYiSage__dsh-purge#card-en
- dsh-market/dsh-market: missing card: /data/dsh-plugin-analysis/results/cards/dsh-market__dsh-market.json
- zhu1090093659/dsh-web: missing card: /data/dsh-plugin-analysis/results/cards/zhu1090093659__dsh-web.json
- superdesigndev/treg: missing card: /data/dsh-plugin-analysis/results/cards/superdesigndev__treg.json
- ccch1mneyyy/dsh-TUI: missing card: /data/dsh-plugin-analysis/results/cards/ccch1mneyyy__dsh-TUI.json
- yjh051108/dsh-routing-suite: JSON parse: JSONDecodeError: Extra data: line 169 column 2 (char 3944)
- MeteorNOX/DeepSeek-Balance-Whale-Widget: A-tier intent count 7 not 8..12; card length 355: MeteorNOX__DeepSeek-Balance-Whale-Widget#card-en
- elysia395/dsh-wallpaper-engine: card length 410: elysia395__dsh-wallpaper-engine#card-en; caveat length 142: elysia395__dsh-wallpaper-engine#caveat-1; caveat length 141: elysia395__dsh-wallpaper-engine#caveat-2; caveat length 137: elysia395__dsh-wallpaper-engine#caveat-3
- T-Auto/dsh-ops: missing card: /data/dsh-plugin-analysis/results/cards/T-Auto__dsh-ops.json
- omdsh-dev/DSH-better-sidebar: card length 139: omdsh-dev__DSH-better-sidebar#card-zh-0; card length 371: omdsh-dev__DSH-better-sidebar#card-en-1
- liustack/modlens: missing card: /data/dsh-plugin-analysis/results/cards/liustack__modlens.json
- NanmiCoder/dsh-agent-teams: missing card: /data/dsh-plugin-analysis/results/cards/NanmiCoder__dsh-agent-teams.json
- sixtysevenlf/dsh-blender-plugin: missing card: /data/dsh-plugin-analysis/results/cards/sixtysevenlf__dsh-blender-plugin.json

## Recommended specification changes

- STRATEGY/facts schema should define suspicious_counts and state that suspicious contains bounded representative locations; otherwise large repositories create hundreds of repetitive risk checks.
- INDEX-TEXTS should define separate Chinese-character and English-word/character limits. Applying 150-300 characters to English caused repeated otherwise-correct failures.
- Schema/evidence rules need a representation for list-derived maintenance facts (commit count, created_at, pushed_at); forcing file:line evidence makes workers cite unrelated package files.
- facts.config extraction and validator should cover declarative settings, not only environment-variable regexes, or valid configuration claims will be rejected.
- README extraction needs an explicit per-repository cap/deduplication rule. 'all useful sections' produced 2,190 README units across 30 repositories, far above the documented common 2-10.
- Unit count and text-length constraints should move into schema where possible; currently schema accepts outputs that the separate validator rejects.
