"""The ink family's rules, each held on a real window at 60 Hz.

The replay photographs every frame the window repaints with the app's own
`grab()` (the UI lab's `photograph`) and reads each character's ink and
each row's underlines off the picture (`tools.scene_replay.inks`), so a
rule here holds on what a learner sees, wherever the colour is decided.
Every test pins one rule of `rules.toml` (`@pins`) or is its planted break
(`@breaks`). The whole ink matrix is judged by `python -m
tools.scene_replay judge`; these are the quick cases.
"""

import pytest
from PySide6.QtWidgets import QApplication
from tools.scene_replay import drive, plants, properties, streams
from tools.scene_replay.frames import Frame
from tools.scene_replay.rulebook import breaks, pins

from polyglotic_desktop.ui_next.views.caption_window import CaptionLook
from polyglotic_desktop.ui_next.views.lab import CaptionLab
from polyglotic_desktop.ui_next.word_classes import APART_FROM_TEXT

LINKED = "rules/linked-words"


def replay(stream: str, setup: str, plant: str | None = None) -> list[Frame]:
    with plants.planted(plant):
        return list(
            drive.play(streams.load(stream), drive.Setup.named(setup), ink=True)
        )


def _rows(frames: list[Frame], state: str) -> list[object]:
    return [
        row
        for frame in frames
        for row in frame.rows
        if row.state == state and row.paper >= 0
    ]


# --- what was said in its colour, the translation in its own -------------------


@pins("ink.own-colours")
def test_the_replays_colours_are_the_looks_own() -> None:
    look = CaptionLook()
    assert int(look.original.lstrip("#"), 16) == properties.ORIGINAL_INK
    assert int(look.translation.lstrip("#"), 16) == properties.TRANSLATION_INK


OWN = [
    (LINKED, "panel+links"),
    (LINKED, "zones+links"),
    (LINKED, "cards+links"),
    (LINKED, "joined+links"),
    (LINKED, "video-instant+links"),
    (LINKED, "video-scrolling+links"),
    ("lines/a", "panel+narrow+links"),
    ("rebuild/two_speakers", "panel+links"),
]


@pins("ink.own-colours")
@pytest.mark.parametrize(("stream", "setup"), OWN)
def test_each_row_is_in_its_own_colour(
    qapp: QApplication, stream: str, setup: str
) -> None:
    frames = replay(stream, setup)
    assert _rows(frames, "finished"), "no finished caption was photographed"
    assert properties.own_colours(frames) == []


@pins("ink.own-colours")
def test_the_transcript_is_where_rows_take_the_interfaces_colours(
    qapp: QApplication,
) -> None:
    """The rule's one exception, pinned so it stays the only one until the
    transcript takes the live style: its translation is the interface's
    grey, not the gold."""
    broken = properties.own_colours(replay(LINKED, "transcript+links"))
    assert broken and all("translation" in b.what for b in broken)


@breaks("ink.own-colours")
def test_swapped_colours_are_seen(qapp: QApplication) -> None:
    broken = properties.own_colours(replay(LINKED, "panel+links", "swap-inks"))
    assert broken and "not in its own colour" in broken[0].what


# --- text still being spoken is fainter ----------------------------------------

SPOKEN = [
    (LINKED, "panel+links"),
    (LINKED, "joined+links"),
    (LINKED, "panel+narrow+links"),
    (LINKED, "video-instant+links"),
    ("lines/a", "panel+links"),
    ("rebuild/live_supersedes_words", "panel+links"),
]


@pins("ink.fainter-while-spoken")
@pytest.mark.parametrize(("stream", "setup"), SPOKEN)
def test_text_still_being_spoken_is_fainter(
    qapp: QApplication, stream: str, setup: str
) -> None:
    frames = replay(stream, setup)
    assert _rows(frames, "live"), "no caption still being spoken was photographed"
    assert properties.fainter_while_spoken(frames) == []


@breaks("ink.fainter-while-spoken")
def test_a_live_caption_in_full_ink_is_seen(qapp: QApplication) -> None:
    broken = properties.fainter_while_spoken(
        replay(LINKED, "panel+links", "full-while-spoken")
    )
    assert broken and "full ink" in broken[0].what


# --- older captions step back ---------------------------------------------------


@pins("ink.older-captions-step-back")
def test_a_caption_is_new_for_the_time_the_rulebook_allows() -> None:
    assert CaptionLab().new_for <= properties.NEW_FOR


STEPS = [
    (LINKED, "panel+links"),
    (LINKED, "joined+links"),
    (LINKED, "cards+links"),
    ("lines/a", "panel+links"),
    ("lines/b", "panel+links"),
]


@pins("ink.older-captions-step-back")
@pytest.mark.parametrize(("stream", "setup"), STEPS)
def test_older_captions_step_back(qapp: QApplication, stream: str, setup: str) -> None:
    frames = replay(stream, setup)
    assert properties.older_step_back(frames) == []


@breaks("ink.older-captions-step-back")
def test_older_captions_as_bright_as_the_newest_are_seen(qapp: QApplication) -> None:
    broken = properties.older_step_back(replay(LINKED, "panel+links", "no-step-back"))
    assert broken and "not stepped back" in broken[0].what


# --- a word link is one colour at both ends -----------------------------------

LINKS = [
    (LINKED, "panel+links"),
    (LINKED, "panel+narrow+links"),
    (LINKED, "zones+links"),
    (LINKED, "joined+links"),
    (LINKED, "video-instant+links"),
    (LINKED, "video-scrolling+links"),
    ("rebuild/mandarin_to_english", "panel+links"),
]


@pins("ink.a-link-is-one-colour")
@pytest.mark.parametrize(("stream", "setup"), LINKS)
def test_a_link_is_one_colour_at_both_ends(
    qapp: QApplication, stream: str, setup: str
) -> None:
    frames = replay(stream, setup)
    assert any(row.bars for frame in frames for row in frame.rows), "no link drawn"
    assert properties.one_link_colour(frames) == []


@pins("ink.a-link-is-one-colour")
@pytest.mark.xfail(
    strict=True,
    reason="the card stack draws a caption still being spoken in full ink and"
    " the underlines of its finished clauses faint (rules.toml: the rule's"
    " conflict with Text still being spoken is fainter)",
)
def test_a_link_is_one_colour_in_the_card_stack_while_spoken(
    qapp: QApplication,
) -> None:
    assert properties.one_link_colour(replay(LINKED, "cards+links")) == []


@pins("ink.a-link-is-one-colour")
def test_the_transcript_draws_no_word_links(qapp: QApplication) -> None:
    """Where the rule does not hold: the transcript draws no links at all."""
    frames = replay(LINKED, "transcript+links")
    assert _rows(frames, "finished")
    assert not any(row.bars for frame in frames for row in frame.rows)


@breaks("ink.a-link-is-one-colour")
def test_a_translation_linked_in_another_colour_is_seen(qapp: QApplication) -> None:
    broken = properties.one_link_colour(replay(LINKED, "panel+links", "shifted-links"))
    assert broken and "counterpart" in broken[0].what


# --- link colours stay clear of the text ----------------------------------------


@pins("ink.links-clear-of-the-text")
def test_the_distance_kept_from_the_text_is_the_one_the_rulebook_states() -> None:
    assert APART_FROM_TEXT == properties.APART_FROM_TEXT


@pins("ink.links-clear-of-the-text")
@pytest.mark.parametrize("setup", ["panel+links", "joined+links", "cards+links"])
def test_no_link_reads_like_its_rows_text(qapp: QApplication, setup: str) -> None:
    frames = replay(LINKED, setup)
    drawn = {
        colour for frame in frames for row in frame.rows for *_, colour in row.bars
    }
    assert drawn, "no link drawn"
    assert properties.links_clear_of_the_text(frames) == []


@breaks("ink.links-clear-of-the-text")
def test_the_orange_beside_the_gold_is_seen(qapp: QApplication) -> None:
    broken = properties.links_clear_of_the_text(
        replay(LINKED, "panel+links", "links-near-the-text")
    )
    assert broken and "reads like" in broken[0].what


# --- no links on the clause still being spoken ----------------------------------


@pins("ink.no-links-while-spoken")
@pytest.mark.parametrize(
    "setup", ["panel+links", "joined+links", "video-instant+links", "zones+links"]
)
def test_a_caption_still_being_spoken_has_no_links(
    qapp: QApplication, setup: str
) -> None:
    frames = replay(LINKED, setup)
    assert _rows(frames, "live"), "no caption still being spoken was photographed"
    assert properties.no_links_while_spoken(frames) == []


@breaks("ink.no-links-while-spoken")
def test_a_live_caption_linked_is_seen(qapp: QApplication) -> None:
    broken = properties.no_links_while_spoken(
        replay(LINKED, "panel+links", "links-while-spoken")
    )
    assert broken and "still being spoken" in broken[0].what
