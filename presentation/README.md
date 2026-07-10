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
- **The T. rex logo** — the gold medallion currently shows a placeholder emoji.
  To use the real artwork, find this block:

  ```html
  <div class="medallion"><span>🦖</span></div>
  ```

  and replace it with an image:

  ```html
  <div class="medallion"><img src="trex-logo.svg" alt="LitReX T. rex logo"
       style="width:76%;height:76%;object-fit:contain"></div>
  ```

  Put `trex-logo.svg` (or `.png`) in this folder. **Note:** a relative path
  means the file is no longer a single self-contained document — to keep it
  shareable as one file, embed the image as a `data:` URI instead (ask and it
  can be inlined). Then update the credit line just below the medallion
  (`.mark-cap`) with the artist's name.

## Provenance

All metrics are real, measured on a held-out 10% test split. The EGFR → NSCLC
example sentence is illustrative, not a specific data row. Corpus-scale figures
("tens of millions of papers", "more than three hundred years") are deliberately
rounded and defensible (PubMed ≈ 35–38M articles; ~5 min/paper, nonstop ≈ 340
years). See [`../docs/19-session-log-outreach-page.md`](../docs/19-session-log-outreach-page.md).
