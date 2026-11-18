"""Unit tests: textprep (PRD §6)."""

from app.audio.textprep import est_duration, normalize, split_sentences


def test_normalize_strips_urls():
    assert normalize("see https://example.com/x?y=1 now") == "see link now"


def test_normalize_collapses_whitespace():
    assert normalize("a\n\n  b\tc") == "a b c"


def test_split_english_sentences():
    out = split_sentences("Hello there. How are you? I am fine!")
    assert out == ["Hello there.", "How are you?", "I am fine!"]


def test_split_bangla_dari():
    out = split_sentences("আমি ভালো আছি। তুমি কেমন আছো?")
    assert out == ["আমি ভালো আছি।", "তুমি কেমন আছো?"]


def test_split_cjk():
    out = split_sentences("你好。很高兴见到你！")
    assert out == ["你好。", "很高兴见到你！"]


def test_no_empty_pieces():
    assert split_sentences("...") == ["..."]
    assert split_sentences("") == []


def test_long_sentence_hard_split():
    text = " ".join(["word"] * 200)  # ~1000 chars, no enders
    out = split_sentences(text, max_chars=300)
    assert all(len(s) <= 310 for s in out)
    assert len(out) >= 3


def test_est_duration_floor():
    assert est_duration("hi") >= 0.4
