# 08 — Product Vision (Light Plan)

**Status:** deliberately brief. In scope for LitReX eventually, but not
designed in detail now — revisit once stage 7's scored relationships exist
and their quality/distribution is known. Treat everything below as
direction, not a spec.

## Front-end: target–disease relationship breakdown

When a user clicks a target/disease "dot" in the platform UI, show:

- % of papers for each relationship category (from the classifier's
  output), for that specific target-disease pair.
- "In papers that mention this target, X% also mention this disease."
- "In papers that mention this disease, X% also mention this target."
  (co-mention stats, independent of relation classification — just
  Cooccurrence-level counting.)
- Whether the supporting publication(s) are also found in other
  datasources (cross-reference using `publication_id`/source across
  Cooccurrence + GWAS Catalog + whatever else lands in the combined
  dataset).

## Evidence score revision

Current state: evidence score is based on which section of a paper the
text was found in, then summed per publication.

Direction: revise scoring to incorporate the classified relationship
(and its confidence) — e.g. a high-confidence "positive" relation should
likely weigh differently than a "neutral" co-mention with no real
relationship claimed. Exact formula is not decided; this is flagged as a
follow-up design task once real classifier output/confidence distributions
are available to calibrate against.

## Why this is deferred

Both of the above depend on knowing the actual shape of the classifier's
output (label distribution, confidence calibration, error rate) from stages
5–7. Designing the UI/scoring formula before that data exists risks
designing against assumptions that don't hold. This doc exists so the
direction isn't lost, not to lock in a design now.

## Revisit trigger

Come back to this doc once stage 7 (inference) has run on at least the
larger pyspark validation sample and produced real output to look at.
