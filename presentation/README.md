# LitReX — outreach page

A single, self-contained HTML page that explains the LitReX pipeline and results
to a **mixed audience** (Carl Sagan register), with a technical appendix for the
specialists. Built for sharing — one file, no dependencies.

**File:** [`LitReX-Reading-the-Biomedical-Cosmos.html`](LitReX-Reading-the-Biomedical-Cosmos.html)

## Open it

Double-click the `.html` file — it opens in any browser and works **fully
offline** (all styles, the starfield, and the layout are inline; nothing is
fetched from the internet). It follows the viewer's light/dark theme.

## Edit it

Everything is in that one file. No build step.

- **Text** — each section is a `<section class="chapter">`. Edit the prose in
  place. Keep paragraphs short; the audience is mixed.
- **Numbers** — every figure comes from the model card (see
  [`../docs/16-session-log-stage6-training.md`](../docs/16-session-log-stage6-training.md)).
  If the model is retrained, update the scorecard, the per-class bars
  (`data-w="…"`), and the technical appendix to match.
- **The T. rex logo** — the gold medallion embeds `litrex_logo.png` inline as
  a `data:` URI, so the page stays a single self-contained file. To swap the
  artwork, replace the `data:image/...;base64,…` string in the `<img src="…">`
  inside the `.medallion` block (search for `class="medallion"`), and update
  the credit line just below it (`.mark-cap`) with the new artist's name.
  Keep the source image (`litrex_logo.png`) in this folder too, for reference
  and for re-encoding if it changes.

## Provenance

All metrics are real, measured on a held-out 10% test split. The EGFR → NSCLC
example sentence is illustrative, not a specific data row. Corpus-scale figures
("tens of millions of papers", "more than three hundred years") are deliberately
rounded and defensible (PubMed ≈ 35–38M articles; ~5 min/paper, nonstop ≈ 340
years). See [`../docs/19-session-log-outreach-page.md`](../docs/19-session-log-outreach-page.md).
