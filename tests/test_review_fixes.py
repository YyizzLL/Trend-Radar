import pytest
from src.judge.works import works_ratio, looks_like_title, _hits
from src.normalize.songmatch import song_in_text
from src.store.lifecycle import Lifecycle, similarity, _lcs_len
from src.deliver.email_html import _summary
from src.deliver.digest import Digest
from src.llm.phrases import _overlap


def test_works_ascii_boundary():
    # "kpop", "top", "cute", "red" should not match work cues like "op", "cut", "ed"
    assert "op" not in _hits("kpop dance cover")
    assert "cut" not in _hits("cute girl video")
    assert "ed" not in _hits("red dress stage")
    # Exact word match should match
    assert "op" in _hits("animation op song")
    assert "cut" in _hits("drama stage cut video")


def test_song_in_text_boundary():
    song = {"name": "With", "artists": ["IU"]}
    # "with" in text without #With or IU shouldn't match
    assert not song_in_text("walking with my friend today", song)
    # "stadium" shouldn't trigger artist "IU"
    assert not song_in_text("huge stadium concert with friends", song)
    # Genuine match
    assert song_in_text("IU new song With stage", song)
    assert song_in_text("listening to #With today", song)


def test_lifecycle_similarity():
    assert similarity("你就这样闯进我", "就这样闯进我的心窝") >= 0.6
    assert similarity("我要逮捕你", "你被逮捕了") == 0.0


def test_llm_overlap():
    assert _overlap("一路打拼终抵百场", "周深厦门演唱") < 0.5
    # Non-CJK alone should not bypass
    assert _overlap("Awesome concert!", "周深厦门演唱") < 0.5
    # Genuine overlap
    assert _overlap("你被逮捕了！", "逮捕") >= 0.5


def test_email_summary_includes_text():
    d = Digest(date="2026-11-26", generated_at="12:00:00")
    d.text_entries = [{"text": "sentence 1"}]
    html = _summary(d)
    assert '今日文案</div>' in html
    assert '>1</div>' in html
