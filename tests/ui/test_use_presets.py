"""Presets for use cases (polyglotic-hq 556, decision 0264): picking one
writes its values; every change made while one is chosen is saved into it
at once; a new install starts on Everyday; a setup from before presets
becomes Custom with nothing lost."""

from collections.abc import Mapping
from dataclasses import replace

from tests.ui.fakes import MemorySettingsStore

from polyglotic_desktop.ui import use_presets
from polyglotic_desktop.ui.settings import AppSettings, Settings
from polyglotic_desktop.ui.use_presets import (
    CONVERSATION,
    CUSTOM,
    EVERYDAY,
    LEARNING,
    VIDEO,
)


def _settings(stored: Mapping[str, object] | None = None) -> Settings:
    return Settings(MemorySettingsStore(dict(stored or {})))


def test_a_new_install_starts_on_everyday_with_nothing_changed() -> None:
    settings = _settings()
    assert settings.value.preset == EVERYDAY
    assert settings.value.preset_values == {} and settings.value.own_presets == ()


def test_a_file_from_before_presets_with_nothing_chosen_is_everyday() -> None:
    value = _settings({"changed": [], "theme": "glaze"}).value  # not a preset's
    assert value.preset == EVERYDAY and CUSTOM not in value.own_presets


def test_picking_video_sets_its_subtitles_and_takes_links_and_readings_off() -> None:
    settings = _settings()
    settings.change(use_presets.chosen(settings.value, VIDEO))
    value = settings.value
    assert value.preset == VIDEO
    assert value.subtitles and value.word_links == "off"
    assert (
        value.reading_lines == () and "reading_lines" in value.changed
    )  # none, chosen
    assert not value.show_source and not value.show_language
    assert value.my_speech is False


def test_a_change_in_a_preset_is_saved_into_it_and_comes_back() -> None:
    settings = _settings()
    settings.change(use_presets.chosen(settings.value, VIDEO))
    settings.update(word_links="arrows", subtitle_size=2.0)  # links on, in Video
    assert settings.value.preset_values[VIDEO] == {
        "word_links": "arrows",
        "subtitle_size": 2.0,
    }
    settings.change(use_presets.chosen(settings.value, CONVERSATION))
    assert settings.value.word_links == "hover"  # Conversation's own
    assert not settings.value.subtitles
    settings.change(use_presets.chosen(settings.value, VIDEO))
    assert settings.value.word_links == "arrows"  # as it was left
    assert settings.value.subtitle_size == 2.0


def test_the_change_is_in_the_file_at_once() -> None:
    store = MemorySettingsStore({})
    settings = Settings(store)
    settings.change(use_presets.chosen(settings.value, LEARNING))
    settings.update(translation_after=3.5)
    saved = store.load()
    assert saved["preset"] == LEARNING
    assert saved["preset_values"] == {LEARNING: {"translation_after": 3.5}}
    again = Settings(store).value  # read again: the same
    assert again.preset == LEARNING and again.translation_after == 3.5
    assert again.caption_path == "acquisition"


def test_a_preset_takes_everydays_colours_unless_it_names_them() -> None:
    settings = _settings()
    settings.update(translation_color="#5ee3ff", opacity=0.9)  # in Everyday
    settings.change(use_presets.chosen(settings.value, VIDEO))
    assert settings.value.translation_color == "#5ee3ff"  # Everyday's
    assert settings.value.opacity == 0.0  # Video names its panel: none


def test_a_file_from_before_presets_becomes_custom_with_nothing_lost() -> None:
    old = {  # 0.1.9's: a record of changes, links turned off, a colour picked
        "changed": ["word_links", "translation_color", "show_source"],
        "word_links": "off",
        "translation_color": "#5ee3ff",
        "show_source": False,
        "fade_after": 8.0,  # 0.1.7 and before kept every key as chosen too
    }
    value = _settings(old).value
    assert value.preset == CUSTOM and value.own_presets == (CUSTOM,)
    assert value.word_links == "off" and value.translation_color == "#5ee3ff"
    assert value.preset_values[CUSTOM] == {
        "word_links": "off",
        "translation_color": "#5ee3ff",
        "show_source": False,
        "fade_after": 8.0,
    }
    # and Conversation, picked and left, gives it all back
    settings = _settings(old)
    settings.change(use_presets.chosen(settings.value, CONVERSATION))
    assert settings.value.word_links == "hover" and settings.value.show_source
    settings.change(use_presets.chosen(settings.value, CUSTOM))
    assert settings.value.word_links == "off" and not settings.value.show_source


def test_a_setting_that_follows_the_default_keeps_following_it() -> None:
    settings = _settings()
    settings.change(use_presets.chosen(settings.value, VIDEO))  # names word links
    settings.change(use_presets.chosen(settings.value, EVERYDAY))
    assert "word_links" not in settings.value.changed  # follows the app's again
    assert "reading_lines" not in settings.value.changed
    assert settings.value.word_links == AppSettings().word_links


def test_readings_all_off_in_everyday_is_kept_as_a_choice() -> None:
    settings = _settings()
    settings.update(reading_lines=("zh",))
    settings.update(reading_lines=())  # every reading off: a choice, at ()
    assert "reading_lines" in settings.value.preset_values[EVERYDAY]
    settings.change(use_presets.chosen(settings.value, LEARNING))
    settings.change(use_presets.chosen(settings.value, EVERYDAY))
    assert "reading_lines" in settings.value.changed  # still none, not the default


def test_reset_drops_what_was_changed_in_it() -> None:
    settings = _settings()
    settings.change(use_presets.chosen(settings.value, VIDEO))
    settings.update(opacity=0.8, subtitle_width=0.6)
    settings.change(use_presets.reset(settings.value, VIDEO))
    assert settings.value.opacity == 0.0 and settings.value.subtitle_width == 0.8
    assert VIDEO not in settings.value.preset_values


def test_an_own_preset_is_a_copy_named_and_chosen() -> None:
    settings = _settings()
    settings.change(use_presets.chosen(settings.value, VIDEO))
    settings.update(word_links="arrows")
    settings.change(use_presets.added(settings.value, "Anime"))
    value = settings.value
    assert value.preset == "own1" and value.own_presets == ("own1",)
    assert value.preset_names["own1"] == "Anime"
    assert value.subtitles and value.word_links == "arrows"  # Video as it was
    settings.change(use_presets.chosen(value, EVERYDAY))
    settings.change(use_presets.chosen(settings.value, "own1"))
    assert settings.value.subtitles and settings.value.word_links == "arrows"
    settings.change(use_presets.removed(settings.value, "own1"))
    assert settings.value.preset == EVERYDAY and settings.value.own_presets == ()
    assert not settings.value.subtitles


def test_no_more_than_five_of_ones_own() -> None:
    value = AppSettings()
    for n in range(7):
        value = use_presets.added(value, f"Mine {n}")
    assert len(value.own_presets) == use_presets.OWN_MOST


def test_a_rename_and_back_to_its_own_name() -> None:
    value = use_presets.renamed(AppSettings(), VIDEO, "  Films  ")
    assert value.preset_names == {VIDEO: "Films"}
    assert use_presets.renamed(value, VIDEO, "").preset_names == {}


def test_a_rollbacks_change_wins_over_the_preset_saved() -> None:
    settings = _settings()
    settings.change(use_presets.chosen(settings.value, VIDEO))
    stored = settings.value.to_stored()
    stored["opacity"] = 0.7  # an older version moved the panel after a rollback
    value = _settings(stored).value
    assert value.preset == VIDEO and value.opacity == 0.7
    assert value.preset_values[VIDEO] == {"opacity": 0.7}


def test_stored_presets_not_valid_are_dropped() -> None:
    stored = {
        "preset": "own9",  # no such preset
        "preset_values": {
            VIDEO: {"opacity": "solid", "word_links": "arrows", "theme": "glaze"},
            "nobody": {"opacity": 0.5},
        },
        "preset_names": {VIDEO: "  ", LEARNING: "Study"},
    }
    value = _settings(stored).value
    assert value.preset == EVERYDAY
    assert value.preset_values == {VIDEO: {"word_links": "arrows"}}  # the valid
    assert value.preset_names == {LEARNING: "Study"}


def test_every_preset_setting_is_a_setting() -> None:
    names = set(AppSettings.__dataclass_fields__)
    assert set(use_presets.PRESET_SETTINGS) <= names
    for named in use_presets.BUILT_IN.values():
        assert set(named) <= set(use_presets.PRESET_SETTINGS)
        replace(AppSettings(), **named)  # type: ignore[arg-type]  # each takes it
