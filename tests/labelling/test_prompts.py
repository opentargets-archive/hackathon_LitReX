from litrex.labelling.prompts import SYSTEM_PROMPT, build_prompt


def test_build_prompt_includes_target_disease_and_text():
    prompt = build_prompt("EGFR", "NSCLC", "some evidence text")
    assert "EGFR" in prompt
    assert "NSCLC" in prompt
    assert "some evidence text" in prompt


def test_build_prompt_no_spans_leaves_text_unmarked():
    prompt = build_prompt("EGFR", "NSCLC", "EGFR is amplified in NSCLC.")
    assert "[[" not in prompt


def test_build_prompt_marks_target_and_disease_spans():
    text = "EGFR is amplified in NSCLC."
    prompt = build_prompt(
        "EGFR", "NSCLC", text, target_span=(0, 4), disease_span=(21, 26)
    )
    assert "[[EGFR]]" in prompt
    assert "[[NSCLC]]" in prompt


def test_build_prompt_skips_marking_overlapping_spans():
    text = "EGFR-NSCLC axis"
    prompt = build_prompt("EGFR", "NSCLC", text, target_span=(0, 9), disease_span=(5, 10))
    assert "[[" not in prompt
    assert text in prompt


def test_build_prompt_skips_marking_out_of_bounds_span():
    text = "short text"
    prompt = build_prompt("EGFR", "NSCLC", text, target_span=(0, 100))
    assert "[[" not in prompt
    assert text in prompt


def test_system_prompt_avoids_fixed_taxonomy_and_defines_grounding_rules():
    # Must not steer the model toward a preset taxonomy -- classification is
    # explicitly deferred to a later step; only free-text description here.
    for label in ["positive-upregulation", "positive-downregulation"]:
        assert label not in SYSTEM_PROMPT
    assert "own words" in SYSTEM_PROMPT
    assert "later step" in SYSTEM_PROMPT
    assert "evidence_span" in SYSTEM_PROMPT
    assert "outside knowledge" in SYSTEM_PROMPT
