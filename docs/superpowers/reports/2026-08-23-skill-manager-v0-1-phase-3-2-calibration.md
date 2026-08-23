# Skill Manager V0.1 Phase 3.2 Calibration Snapshot

Observed on 2026-08-23 from `/Users/jana/.agents/skills` and
`/Users/jana/.codex/skills`. This is a read-only semantic-review sample, not
a Decision Registry: it neither suppresses warnings nor authorizes actions.

The L0 score is only a candidate-ranking signal. The final relationship below
was reviewed against each pair's `SKILL.md` primary purpose, core work,
incidental mentions, and structural parent relationship.

| # | Category | Skill A | Skill B | L0 | Reviewed relationship | Scope / key evidence |
|--:|---|---|---|---:|---|---|
| 1 | Design | ui-styling | ui-ux-pro-max | 0.6800 | high-overlap | peer; both design and implement accessible responsive UI, with different libraries/data |
| 2 | Design | design-system | slides | 0.6430 | partial-overlap | peer; tokens support slides, but component system and presentation creation remain distinct |
| 3 | Design | design | slides | 0.5727 | partial-overlap | generalist-specialist; broad design includes slides, specialised skill produces strategic HTML presentations |
| 4 | Design | slides | ui-styling | 0.5171 | partial-overlap | peer; both use visual layouts, but presentation outputs differ from application UI |
| 5 | Design | design | ui-ux-pro-max | 0.4857 | partial-overlap | generalist-specialist; broad asset/design work versus UI/UX intelligence |
| 6 | Design | banner-design | design | 0.4350 | partial-overlap | generalist-specialist; campaign banner execution is one design surface |
| 7 | Design | brand | design-system | 0.2169 | complementary | brand voice/identity versus tokens/components; shared visual vocabulary is incidental |
| 8 | Design | design-taste-frontend | ui-styling | 0.1700 | partial-overlap | peer; frontend visual refinement versus shadcn/Tailwind component implementation |
| 9 | Design | banner-design | brand | 0.2195 | complementary | a banner consumes brand direction; it does not define brand governance |
| 10 | Content | space-xhs-writer | space-xhs-title | 0.0000 | complementary | body writing explicitly delegates title generation to the title skill |
| 11 | Content | space-xhs-title | baokuan-title-generator | 0.0000 | high-overlap | peer; both generate, score, and recommend headline alternatives, differentiated chiefly by platform/methodology |
| 12 | Content | space-xhs-buddy | space-xhs-writer | 0.0000 | complementary | generalist-specialist; workflow routing versus one writing stage |
| 13 | Content | global-content-search | baokuan-article-analysis | 0.0000 | partial-overlap | peer; content retrieval and article analysis meet at research but have different final work |
| 14 | Content | space-xhs-writer | global-content-search | 0.0000 | unrelated | writing an XHS post versus read-only cross-platform retrieval; no shared core deliverable |
| 15 | Video | creator-buddy | space-video | 0.0000 | parent-child | direct Inventory hierarchy; never a duplicate candidate |
| 16 | Video | creator-buddy | space-video-script | 0.0000 | parent-child | direct Inventory hierarchy; never a duplicate candidate |
| 17 | Video | creator-buddy | space-video-subtitle | 0.0000 | parent-child | direct Inventory hierarchy; never a duplicate candidate |
| 18 | Video | space-video | space-video-edit | 0.2400 | complementary | generalist-specialist; director routes a pipeline, editor performs one production stage |
| 19 | Video | space-video-script | space-video-edit | 0.0000 | complementary | adjacent workflow stages: spoken script/storyboard versus edit/export |
| 20 | Video | space-video-edit | space-video-subtitle | 0.3825 | partial-overlap | peer; edit can include subtitles, while subtitle skill owns transcription and SRT/ASS quality |
| 21 | Video | space-video-broll | space-video-cover | 0.0000 | unrelated | animated B-roll production versus static platform thumbnail design |
| 22 | Research / Tool | agent-reach | global-content-search | 0.0000 | complementary | generalist-specialist; internet retrieval infrastructure versus content-platform search workflow; Agent Reach is a dependency, not duplicate work |
| 23 | Research / Tool | agent-reach | find-skills | 0.0000 | unrelated | external-content research versus discovery of installable agent skills |
| 24 | Research / Tool | agent-reach | space-video | 0.4250 | unrelated | `video` is an incidental search target for Agent Reach, not video-production capability |
| 25 | Research / Tool | find-skills | global-content-search | 0.0000 | unrelated | skill discovery versus content search despite shared English “find/search” terms |
| 26 | Custom / Agent | personal-context-router | ponytail | 0.0000 | uncertain | both profiles lack reliable structured capability sections; routing memory context versus minimal-code policy is not forced into a relation |
| 27 | Custom / Agent | personal-context-router | agent-reach | 0.0000 | uncertain | limited structured evidence; personal context and internet research appear distinct but are left for manual confirmation |

## Counts

- Reviewed pairs: 27
- `high-overlap`: 2
- `partial-overlap`: 8
- `complementary`: 7
- `unrelated`: 5
- `parent-child`: 3
- `uncertain`: 2
- `duplicate`: 0

Five Design L0 high/near-high candidates (#1–#5) were deliberately reviewed;
only #1 remained `high-overlap`. In particular, broad `design` and the
`design-system ↔ slides` pair were not allowed to become duplicates.

## Cross-language and incidental-evidence checks

- The unit semantic case accepts Chinese `前端视觉优化` and English `frontend
  visual refinement` as evidence-backed `high-overlap`.
- `agent-reach ↔ global-content-search` checks Chinese/English mixed source
  material without mistaking a dependency relationship for duplication.
- `agent-reach ↔ space-video` is the core-vs-incidental regression check:
  mentioning YouTube/video search does not confer video-production capability.
- `find-skills ↔ global-content-search` checks that shared English search/find
  terminology with distinct output responsibilities remains `unrelated`.
