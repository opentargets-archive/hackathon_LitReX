from litrex.labelling.prompts import build_prompt


def test_build_prompt_includes_target_disease_and_text():
    prompt = build_prompt("EGFR", "NSCLC", "some evidence text")
    assert "EGFR" in prompt
    assert "NSCLC" in prompt
    assert "some evidence text" in prompt
