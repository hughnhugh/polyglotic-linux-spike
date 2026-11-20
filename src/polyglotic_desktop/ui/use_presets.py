"""Presets for use cases (polyglotic-hq 556; desktop decision 0264): named
ways of using captions - Everyday, Conversation, Video, Learning, Custom
(a setup from before presets) and the learner's own - each holding the
values of the caption settings named in `PRESET_SETTINGS`. Plain Python
over `AppSettings`, no Qt.

- **Everyday is the base:** the app's defaults - every helper on (478,
  555) - with whatever the learner changes in it, and where a new install
  starts (Claude for the user, 2026-11-20: starting on "Custom" when
  nothing was customised reads wrong).
- **A preset names only what it's about** (`BUILT_IN`) and takes the rest
  from Everyday: so a learner's colours and timing chosen there follow
  them into Video until they change them in Video.
- **Custom** is a learner's setup from before presets (`from_flat`), kept
  whole and chosen, so nothing they chose is lost and nothing on screen
  changes; it is there only for a learner who had changed something.
- **Every change made while a preset is chosen is saved into it at once**
  (`saved_into`, from `Settings.update`): its own changes are what differs
  from what it would have (`base_of`), kept by its key in
  `AppSettings.preset_values`.
- **Picking one** (`chosen`) writes its values over the settings, so
  everything that reads a setting - the caption windows, Settings, the
  server's languages - follows without knowing about presets.
- **The settings file keeps the chosen preset's values as always**, one key
  each: an older version reads them, and they win when this one reads the
  file again (a change made after a rollback is kept) - the chosen
  preset's own changes are worked out from them (`from_flat`).
- **A setting that follows the app's default** (`FOLLOW_DEFAULT`, decision
  0220) keeps following it in a preset that doesn't name it, and is "a
  choice" in one that does (Video's no readings).

Holds no caption text.
"""

from collections.abc import Mapping
from dataclasses import fields, replace
from typing import Any

from polyglotic_desktop.ui.settings import (
    FOLLOW_DEFAULT,
    AppSettings,
    as_valid,
)

EVERYDAY = "everyday"
CONVERSATION = "conversation"
VIDEO = "video"
LEARNING = "learning"
CUSTOM = "custom"
ORDER = (EVERYDAY, CONVERSATION, VIDEO, LEARNING)
"""The built-in presets, as the bar's dropdown and Settings list them;
Custom (where there is one) and the learner's own follow, in the order
made (`AppSettings.own_presets`)."""
OWN_MOST = 5
"""Presets of the learner's own at most."""
OWN_PREFIX = "own"
"""An own preset's key: "own1", "own2"... - never its name, which is the
learner's words and stays on this PC."""

PRESET_SETTINGS = (
    # what each caption shows
    "show_original",
    "show_translation",
    "show_language",
    "show_source",
    "fade_after",
    # help with words
    "word_links",
    "quiet_view",
    "reading_lines",
    "reading_past",
    "marks_off",
    "common_words_only",
    # the look
    "opacity",
    "original_color",
    "translation_color",
    "background_color",
    "caption_edge",
    "caption_weight",
    "caption_contrast",
    "caption_vibrance",
    # timing
    "caption_mode_chosen",
    "caption_path",
    "translation_after",
    "steady_newest_word",
    "steady_words_ahead",
    "steady_two_zones",
    # the windows
    "subtitles",
    "subtitle_size",
    "subtitle_width",
    "my_speech",
)
"""The settings a preset holds - every one, in every preset. The rest
(languages, sound, dictation, learning, the app's own) are the same in
all of them."""

BUILT_IN: Mapping[str, Mapping[str, object]] = {
    EVERYDAY: {},
    CONVERSATION: {
        "word_links": "hover",  # only the word pointed at: a busy call stays calm
        "steady_newest_word": True,  # a quarter second sooner (DECISIONS #233 B)
        "my_speech": True,  # what you said, as "You", in every window
    },
    VIDEO: {
        "subtitles": True,  # the bottom of the screen, wide, large, two lines
        "word_links": "off",
        "quiet_view": False,
        "reading_lines": (),
        "marks_off": True,
        "show_language": False,
        "show_source": False,
        "fade_after": 4.0,  # gone after the line, as subtitles go
        "opacity": 0.0,  # no box: the letters outlined, as subtitles are
        "caption_edge": "outline",
        "steady_two_zones": False,  # one flow of two lines
        "my_speech": False,
    },
    LEARNING: {
        "caption_path": "acquisition",  # each line first, its translation after
        "word_links": "arrows",
        "quiet_view": False,
        "reading_past": False,
        "marks_off": False,
        "common_words_only": True,
    },
}
"""What each built-in preset names; anything else is Everyday's."""


def is_own(key: str) -> bool:
    """One the learner made (not Custom, which moved over)."""
    return key.startswith(OWN_PREFIX) and key[len(OWN_PREFIX) :].isdigit()


def keys(value: AppSettings) -> tuple[str, ...]:
    """Every preset there is, in the dropdown's order."""
    return (*ORDER, *value.own_presets)


def exists(value: AppSettings, key: str) -> bool:
    return key in ORDER or key in value.own_presets


def can_add(value: AppSettings) -> bool:
    """Another of the learner's own can be made (OWN_MOST; Custom aside)."""
    return sum(1 for key in value.own_presets if is_own(key)) < OWN_MOST


def _defaults() -> dict[str, object]:
    defaults = AppSettings()
    return {name: getattr(defaults, name) for name in PRESET_SETTINGS}


def base_of(value: AppSettings, key: str) -> tuple[dict[str, object], frozenset[str]]:
    """What preset `key` would have without its own changes, and which of
    those values are named - by Everyday's changes or by the preset -
    rather than the app's defaults: Everyday's is the app's defaults; a
    built-in's, Everyday's values with its own named over them; Custom's
    and the learner's own, Everyday's."""
    values = _defaults()
    if key == EVERYDAY:
        return values, frozenset()
    everyday = value.preset_values.get(EVERYDAY, {})
    named = dict(everyday)
    named.update(BUILT_IN.get(key, {}))
    values.update(named)
    return values, frozenset(named)


def values_of(value: AppSettings, key: str) -> tuple[dict[str, object], frozenset[str]]:
    """Preset `key`'s values - what it would have, with its own changes
    over them - and which are named (not the app's defaults)."""
    values, named = base_of(value, key)
    own = value.preset_values.get(key, {})
    values.update(own)
    return values, named | frozenset(own)


def own_changes(value: AppSettings) -> dict[str, object]:
    """The chosen preset's own changes as the settings have them now: each
    preset setting that differs from what the preset would have - and one
    that follows the app's default where the preset doesn't name it, made
    a choice on this PC (`changed`), even at the default's value (the
    learner turned every reading line off: () as a choice)."""
    base, named = base_of(value, value.preset)
    found: dict[str, object] = {}
    for name in PRESET_SETTINGS:
        now = getattr(value, name)
        if name in FOLLOW_DEFAULT:
            chosen = name in value.changed
            if chosen and (name not in named or now != base[name]):
                found[name] = now
            continue
        if now != base[name]:
            found[name] = now
    return found


def saved_into(value: AppSettings) -> AppSettings:
    """`value` with the chosen preset's own changes as its settings are now
    - what every change made while a preset is chosen does (556)."""
    own = own_changes(value)
    kept = {k: v for k, v in value.preset_values.items() if k != value.preset}
    if own:
        kept[value.preset] = own
    if kept == value.preset_values:
        return value
    return replace(value, preset_values=kept)


def chosen(value: AppSettings, key: str) -> AppSettings:
    """`value` with preset `key` chosen: its values over the settings, and
    the record of changes saying which of the settings that follow the
    app's default are named by it (a choice) and which still follow it.
    The preset before keeps its own changes (`saved_into` has them)."""
    if not exists(value, key):
        return value
    value = saved_into(value)
    values, named = values_of(value, key)
    following = {
        name for name in PRESET_SETTINGS if name in FOLLOW_DEFAULT and name not in named
    }
    changed = [name for name in value.changed if name not in following]
    changed += [
        name
        for name in PRESET_SETTINGS
        if name in named and name in FOLLOW_DEFAULT and name not in changed
    ]
    return replace(value, preset=key, changed=tuple(changed), **values)  # type: ignore[arg-type]


def reset(value: AppSettings, key: str) -> AppSettings:
    """Preset `key` without its own changes - and, while it's chosen, its
    values over the settings. Everyday's reset is the app's defaults (every
    preset taking Everyday's values follows); Custom's, Everyday's."""
    kept = {k: v for k, v in value.preset_values.items() if k != key}
    value = replace(value, preset_values=kept)
    if value.preset != key:
        return value
    values, named = values_of(value, key)
    changed = tuple(
        name
        for name in value.changed
        if name not in PRESET_SETTINGS or name not in FOLLOW_DEFAULT or name in named
    )
    return replace(value, changed=changed, **values)  # type: ignore[arg-type]


def added(value: AppSettings, name: str) -> AppSettings:
    """A preset of the learner's own, made from the chosen one as it is now
    and chosen - none past OWN_MOST."""
    if not can_add(value):
        return value
    value = saved_into(value)
    taken = set(value.own_presets)
    number = next(n for n in range(1, OWN_MOST + 2) if f"{OWN_PREFIX}{n}" not in taken)
    key = f"{OWN_PREFIX}{number}"
    names = dict(value.preset_names)
    names[key] = name
    made = replace(
        value,
        own_presets=(*value.own_presets, key),
        preset_names=names,
        preset=key,
    )
    return saved_into(made)


def removed(value: AppSettings, key: str) -> AppSettings:
    """A preset of the learner's own - or Custom - deleted; Everyday chosen
    if it was."""
    if key not in value.own_presets:
        return value
    if value.preset == key:
        value = chosen(value, EVERYDAY)
    return replace(
        value,
        own_presets=tuple(k for k in value.own_presets if k != key),
        preset_values={k: v for k, v in value.preset_values.items() if k != key},
        preset_names={k: v for k, v in value.preset_names.items() if k != key},
    )


def renamed(value: AppSettings, key: str, name: str) -> AppSettings:
    """Preset `key` named `name` - "" takes a built-in one or Custom back
    to its own name (an own preset keeps the one it has)."""
    name = name.strip()[:NAME_MOST]
    names = dict(value.preset_names)
    if name:
        names[key] = name
    elif not is_own(key):
        names.pop(key, None)
    return replace(value, preset_names=names)


NAME_MOST = 40
"""Characters in a preset's name."""


def from_flat(value: AppSettings, before_presets: bool = False) -> AppSettings:
    """The settings as read. A file from before presets (`before_presets`)
    with any preset setting chosen becomes Custom, chosen - its own changes
    every preset setting it records as changed - and one with none, or a
    new install, Everyday. Any file's chosen preset takes its own changes
    from the flat values, which win (a change made by an older version after
    a rollback is kept); presets or values not valid are dropped."""
    if before_presets:
        setup = own_changes(replace(value, preset=EVERYDAY, preset_values={}))
        if setup:
            value = replace(value, preset=CUSTOM, own_presets=(CUSTOM,))
        else:
            value = replace(value, preset=EVERYDAY)
    if not exists(value, value.preset):
        value = replace(value, preset=EVERYDAY)
    kept: dict[str, dict[str, object]] = {}
    for key, own in value.preset_values.items():
        if exists(value, key) and key != value.preset:
            kept[key] = valid_values(own)
    names = {
        k: v[:NAME_MOST]
        for k, v in value.preset_names.items()
        if exists(value, k) and v.strip()
    }
    return saved_into(replace(value, preset_values=kept, preset_names=names))


def valid_values(own: Mapping[str, object]) -> dict[str, object]:
    """A preset's stored changes, each a preset setting and valid for it."""
    defaults = AppSettings()
    found: dict[str, Any] = {}
    names = {f.name for f in fields(AppSettings)}
    for name, stored in own.items():
        if name not in PRESET_SETTINGS or name not in names:
            continue
        valid = as_valid(name, stored, getattr(defaults, name))
        if valid is not None:
            found[name] = valid[0]
    return found


def stored_values(own: Mapping[str, object]) -> dict[str, object]:
    """A preset's changes as the settings file keeps them (lists, not
    tuples)."""
    return {k: list(v) if isinstance(v, tuple) else v for k, v in own.items()}


def differences(value: AppSettings, key: str) -> dict[str, object]:
    """What preset `key` changes, as Settings lists it: each value of its
    that differs from Everyday's - Everyday's, from the app's defaults - and
    a setting that follows the app's default where it names one and
    Everyday doesn't (Video's readings: none, not the default). The chosen
    preset's as the settings are now."""
    values, named = values_of(value, key)
    if key == value.preset:
        values = {name: getattr(value, name) for name in PRESET_SETTINGS}
    if key == EVERYDAY:
        against, against_named = _defaults(), frozenset[str]()
    else:
        against, against_named = values_of(value, EVERYDAY)
    return {
        name: values[name]
        for name in PRESET_SETTINGS
        if values[name] != against[name]
        or (name in FOLLOW_DEFAULT and name in named and name not in against_named)
    }


USAGE_COLOURS = ("original_color", "translation_color", "background_color")
"""Colours are counted as changed, never by their value (556)."""


def usage(value: AppSettings) -> dict[str, str | int | float | bool]:
    """The preset in use as the session summary's optional properties
    (polyglotic-hq 556; polyglotic-server's tracking plan,
    `listening_session_ended`): `preset` - a built-in's key, "custom", or
    "own" for one of the learner's (never its name) - and `preset_<setting>` for each
    setting in it that differs from the preset's own defaults: a fixed
    list's value, a number or a switch. Colours only as changed (True);
    the reading lines as how many are on; fade after quiet 0 for never; my
    speech "on", "off" or "each"; the caption mode "default" while it
    follows the app's. Nothing a learner typed, no caption text."""
    found: dict[str, str | int | float | bool] = {
        "preset": value.preset if value.preset in (*ORDER, CUSTOM) else "own"
    }
    for name, now in own_changes(value).items():
        found[f"preset_{name}"] = _usage_value(name, now)
    return found


def _usage_value(name: str, value: object) -> str | int | float | bool:
    if name in USAGE_COLOURS:
        return True
    if name == "reading_lines":
        return len(value) if isinstance(value, tuple | list) else 0
    if name == "fade_after":
        return float(value) if isinstance(value, int | float) else 0.0
    if name == "my_speech":
        return "each" if value is None else "on" if value else "off"
    if name == "caption_mode_chosen":
        return "default" if value is None else str(value)
    if isinstance(value, bool | str):
        return value
    if isinstance(value, int | float):
        return value
    return str(value)
