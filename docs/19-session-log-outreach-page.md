# 19 — Session log: outreach page

A visual, single-page explainer of the whole LitReX pipeline for a **mixed
audience**, written in a Carl Sagan register, with a technical appendix for
specialists. Lives at
[`presentation/LitReX-Reading-the-Biomedical-Cosmos.html`](../presentation/LitReX-Reading-the-Biomedical-Cosmos.html)
(self-contained; see [`presentation/README.md`](../presentation/README.md) for
how to open and edit).

## What it contains

A scrolling "descent" from the cosmic scale to the molecular:

1. **The library** — the vastness of the unread literature (tens of millions of
   papers; ~300+ years to read at 5 min each, nonstop).
2. **Aside — the tyrant in the name** — the *T. rex* hidden in *LitReX*, and the
   deep-time link (last *T. rex* ≈ 66 Mya ⇄ light from ~66 M light-years away).
   Holds a **placeholder medallion** for the team's T. rex logo.
3. **One kind of sentence** — what a target–disease relation is (worked example).
4. **Five signals** — the taxonomy as a plain-language legend + reliabilities.
5. **Teaching a machine to read** — the pipeline as a numbered sequence; the
   80/10/10 "hide the fifth" test explained simply.
6. **What it learned** — scorecard (accuracy 0.628, weighted-F1 0.619), per-class
   reliability bars, and an honest note on the negative_finding blind spot + the
   √-weighting fix.
7. **The scale to come** — full-corpus vision / Open Targets.
8. **Technical appendix** — collapsible mono spec grid: corpus, silver labels,
   prototype taxonomy, PubMedBERT + entity markers, grouped/stratified split,
   √-inverse weighting via CV sweep, held-out metrics, the `pandas_udf`
   inference path, stack, and known limits.

## Numbers = single source of truth

Every metric is copied from the model card / docs/16 (stage 6) and docs/17
(stage 7), measured on the held-out 10% test set. **If the model is retrained,
update in the HTML:** the three scorecard tiles, the five `.bar-fill data-w`
values + `.bar-val` labels, and the "test metrics" row in the appendix.

## Honesty notes (for anyone editing)

- The EGFR → NSCLC example sentence is **illustrative**, not a data row.
- "Tens of millions of papers" / "more than three hundred years" are rounded and
  defensible (PubMed ≈ 35–38M; ~105k papers/yr at 5 min each ⇒ ~340 yr).
- No star is officially named for a dinosaur; the 66-million-year light-travel
  link is used instead because it is definitionally exact.

## To update the logo

The gold medallion shows a placeholder emoji. Replace the artwork per
[`presentation/README.md`](../presentation/README.md) → "Edit it → The T. rex
logo", and update the credit line (`.mark-cap`) with the artist's name. To keep
the page a single shareable file, embed the image as a `data:` URI.

## Design

Planetarium palette (midnight indigo + Voyager-gold), warm humanist serif for
prose with a mono face for figures, ambient starfield (reduced-motion safe),
scroll-revealed chapters, deliberate twilight light theme. All inline; no
external assets, no build step.
