# 06 — Classifier Training

## Goal

Fine-tune a transformer classifier on the silver-labelled dataset (stage 5)
so relation classification can run at full dataset scale without an LLM
call per row.

## Input

Silver-labelled dataset (`LabeledTriple` rows) from stage 5, plus the
finalized relation taxonomy from that stage's manual review pass.

## Base model

Candidate: a biomedical-domain transformer (PubMedBERT or BioBERT-style).
Not yet confirmed — decide after seeing stage 5's actual label distribution
and text characteristics (see [10-open-questions.md](10-open-questions.md)).

## Steps

1. **Dataset construction**: build train/val/test splits from the silver
   labels. Consider stratifying by relation label (classes are likely
   imbalanced — "neutral"/co-mention-only is probably the majority class)
   and by target/disease to avoid leaking the same target-disease pair
   across splits.
2. **Label encoding**: map the (possibly-expanded) open-vocabulary relation
   labels from stage 5 to a fixed label set for this training run — this is
   where the taxonomy gets "closed" for the purposes of a given model
   version, even though the labelling step upstream stays open-vocabulary
   for future rounds.
3. **Fine-tuning loop**: standard HF `Trainer`-based fine-tuning, input =
   `text` (+ target/disease name, likely marked/highlighted in the input a
   la entity markers), output = relation class (+ confidence/probability).
4. **Evaluation**: accuracy/F1 per class (esp. minority classes), confusion
   matrix, calibration check against the LLM's own confidence scores from
   stage 5 (sanity check: does the classifier agree with the LLM more on
   high-confidence LLM labels?).
5. **Model card**: record base model, taxonomy version/label set, training
   data size, eval metrics — this becomes the reference point for deciding
   when a re-label/re-train cycle is needed later.

## Output

- Trained classifier checkpoint + label encoder/mapping.
- Eval report (metrics above).
- Model card documenting the taxonomy version this model was trained
  against — required so stage 7 (inference) and stage 8 (product) know
  which label set is in play for a given model version.

This output feeds [07-inference.md](07-inference.md).
