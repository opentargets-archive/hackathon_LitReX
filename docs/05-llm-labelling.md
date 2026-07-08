# 05 — LLM Relationship Judge (Labelling)

## Goal

Use an LLM to label each sampled `Cooccurrence` row with the relationship
expressed between its target and disease, producing the silver-label
dataset that stage 6 trains on.

This is a **directed judge**, not open-domain triple extraction: the
subject (target) and object (disease) are already known for every row — the
LLM's job is only to name the relation and how confident it is.

## Provider

Anthropic API (Claude). Swappable later if needed, but the labelling client
should default to Claude — see the `claude-api` reference skill in this
environment for model IDs/pricing/params when implementing the client.

## Input

`sample_manifest.parquet` from stage 4: rows of
`(target, disease, text, publication_id, publication_date, section)`.

## Prompt design

Core prompt shape:

```
In TEXT, what is the relationship between TARGET and DISEASE?
```

Where `TARGET`/`DISEASE` are resolved to human-readable names (not raw IDs)
for the prompt — need a target/disease ID → name lookup (likely available
from the same Open Targets Platform data used for platform totals).

Output per row:

- `relation`: open-vocabulary string label. The model is free to emit a
  label outside the starting taxonomy (positive-upregulation,
  positive-downregulation, negative, neutral) if the text expresses
  something else — do not constrain via enum/closed-set in the prompt for
  v1.
- `confidence`: float 0–1.

Exact prompt wording/output format (plain text vs. structured/tool-call
output) is an implementation detail to nail down when writing the client —
structured output (e.g. via tool use / forced JSON) is recommended so
`relation`/`confidence` parse reliably at scale.

## Output contract

```
LabeledTriple:
  target:           str
  disease:          str
  text:             str
  relation:         str    # open-vocabulary label from the LLM
  confidence:        float  # 0-1
  publication_id:   str
  publication_date: date
```

## Steps

1. Build a batched LLM client (retry/rate-limit handling — sample size is
   small, so cost/latency isn't the bottleneck, correctness of parsing is).
2. Build target/disease ID → display-name lookup for prompt construction.
3. Run the prompt over every row in the sample, parse `relation` +
   `confidence`.
4. **Manual review pass**: inspect a subset of outputs, specifically
   looking for relation labels outside the starting taxonomy — this is the
   explicit reason for doing an open-vocabulary judge rather than a
   closed-set classifier. Decide whether novel labels get folded into the
   taxonomy, merged into an existing category, or kept as-is.
5. Produce the final silver-labelled dataset once the taxonomy question is
   settled for this round (taxonomy can still expand in future rounds).

## Output

Silver-labelled dataset (`LabeledTriple` rows, Parquet) — input to
[06-classifier-training.md](06-classifier-training.md). Also produces an
updated relation taxonomy (may differ from the 4-item starting hypothesis
in [01-overview.md](01-overview.md)) as a side artifact of the manual review
pass.
