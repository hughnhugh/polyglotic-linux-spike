"""What 571's Linux checks count as typed and as found (tools/
linux_typing_check.py, tools/linux_fonts_check.py) - the checks themselves
run on GitHub's Linux runners."""

from tools import linux_fonts_check, linux_typing_check


def _case(name: str) -> linux_typing_check.Case:
    return next(c for c in linux_typing_check.cases("ibus") if c.name == name)


def test_chinese_counts_only_as_the_words_meant() -> None:
    pinyin = _case("pinyin")
    assert linux_typing_check.typed("你好", pinyin)
    assert not linux_typing_check.typed("nihao ", pinyin)
    assert not linux_typing_check.typed("にほんご", pinyin)


def test_japanese_counts_as_typed_in_kana_before_its_conversion() -> None:
    japanese = _case("japanese")
    assert linux_typing_check.typed("日本語", japanese)
    assert linux_typing_check.typed("にほんご", japanese)
    assert not linux_typing_check.typed("nihongo", japanese)


def test_each_mode_types_its_frameworks_pinyin() -> None:
    assert [c.name for c in linux_typing_check.cases("ibus")] == ["pinyin", "japanese"]
    assert [c.name for c in linux_typing_check.cases("ibus-unnamed")] == ["pinyin"]
    assert [c.name for c in linux_typing_check.cases("fcitx5")] == [
        "pinyin",
        "japanese",
    ]
    fcitx5 = linux_typing_check.cases("fcitx5-kubuntu")
    assert [c.name for c in fcitx5] == ["pinyin"]
    assert fcitx5[0].attempts[0].engine == (("fcitx5-remote", "-s", "pinyin"),)


def test_a_languages_findings_name_boxes_and_the_wrong_face() -> None:
    clean = {"language": "ja", "boxes": [], "chinese_in_a_japanese_face": []}
    assert linux_fonts_check.findings(clean) == []
    found = linux_fonts_check.findings(
        {"language": "ja", "boxes": ["⚙ Settings"], "japanese_in_a_chinese_face": ["x"]}
    )
    assert found[0].startswith("boxes: 1") and found[1].startswith("japanese_in")
    assert linux_fonts_check.findings({"error": "no Qt"}) == ["didn't run: no Qt"]


def test_scripts_are_told_apart_by_their_blocks() -> None:
    assert [linux_fonts_check.script_of(c) for c in "日に한ไहЖa1"] == [
        "han",
        "kana",
        "hangul",
        "thai",
        "devanagari",
        "cyrillic",
        "latin",
        "",
    ]
