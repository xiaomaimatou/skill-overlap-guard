# Skill Manager V0.1 Phase 3.3 Candidate Recall Snapshot

Read-only scan on 2026-08-23 of `/Users/jana/.agents/skills` and
`/Users/jana/.codex/skills`, using:

```text
candidate threshold = 0.25
minimum candidates = 5
maximum candidates = 10
```

| Metric | Result |
|---|---:|
| Installed Skills | 40 |
| All pairs | 780 |
| Structural parent-child pairs | 27 |
| Threshold-qualified functional pairs | 29 |
| Semantic candidates selected | 10 |
| Candidate ratio | 1.28% |
| Known positives | 2 |
| Known positives recalled | 2 |
| Known-positive recall | 100% |
| Known-negative candidates | 0 |
| Override candidates selected | 1 |

## Known-positive recheck

| Pair | L0 candidate score | Candidate result | Reason | Semantic result from 3.2 |
|---|---:|---|---|---|
| ui-styling ↔ ui-ux-pro-max | 0.6800 | selected | score threshold | high-overlap |
| space-xhs-title ↔ baokuan-title-generator | 0.0000 | selected override | `normalized_concept_match:title-generation`; `normalized_primary_purpose_match:title-generation` | high-overlap |

The latter proves that selection is no longer tied to exact English token
overlap. Its score is deliberately unchanged; score ranks candidates, while
the explainable override establishes recall.

## Known-negative recheck

| Pair | Semantic result from 3.2 | Selected? | Observation |
|---|---|---|---|
| agent-reach ↔ space-video | unrelated | no | `video` remains incidental to internet search |
| brand ↔ design-system | complementary | no | broad visual/design vocabulary alone did not override |

The 27-pair semantic calibration from Phase 3.2 remains the relationship
reference. It contained two confirmed `high-overlap` pairs and no confirmed
`duplicate`; both HIGH pairs are now in the candidate set. Parent-child pairs
remain structural-only and never consume a normal semantic-review slot.
