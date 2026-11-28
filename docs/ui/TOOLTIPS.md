# Help in one style (polyglotic-hq 1013)

Updated 2026-11-29. Replaces the first audit (2026-11-28, 89 native `setToolTip` calls), whose verdicts were never carried out.

## The rule

Qt's native tooltip is gone from the app. Windows paints it as one long strip across the window, and it repeated what the control already said. Help is now one themed popup, wrapped at about 40 characters a line (`controls.HELP_POPUP_CHARACTERS`), placed beside what it explains and never over it. It shows on resting hover (`HELP_DELAY_MS`, 400 ms), at once on keyboard focus, and on a click of an ⓘ. It can appear in three places only:

| Where | What it holds | Code |
|---|---|---|
| An ⓘ beside a label | An explanation the label needs | `InfoIcon`, `with_info`, `Row(tip=…)`, `SwitchRow(…, tip)` |
| A control that shows no words of its own (an icon, a code like "A+" or "EN ▾", a chip showing its value, a slider, a meter) | Its name | `set_help_tip` |
| A box beside an open menu or dropdown | The highlighted choice's description | `DescribedMenu`, `describe` |

List and table items keep their help in `HELP_ROLE`, never Qt's `ToolTipRole`. `item_help(view)` shows it beside the item, or only when the item's words are cut off if the help is just those words. A caption window is never active, so its strip uses its own label (`strip_tips`), drawn in the same style.

The UI lab's tooltip check (`tools/ui_lab/tooltips.py`, run on every state by `checks.inspect`) fails a state with:
- a native tooltip anywhere Qt could paint one: a widget's, an item's in a list, table, tree or combo box, a tab's, or a menu with `toolTipsVisible`;
- help that repeats words shown in the window;
- help on a label, a labelled control or a row (the help belongs behind an ⓘ);
- a help popup or description box that is wider than the limit or cut off.

`tests/tools/test_ui_lab_tooltips.py` plants each fault. The list-item case is the one the first checker missed, because it only walked widgets.

## Help in the app now

| Where | Kind | Exact English | Lab states |
|---|---|---|---|
| Caption window strip buttons (lock, settings, transcript, fill, aligned, links, stop, bigger, timing modes) | name, strip label | the action's help, for example "Stop captioning {app}", "Lock - clicks pass through to what's underneath, Ctrl+Alt+L", "Word links on or off. Colours show word class.", "Drag the top edge for more lines" / "Bigger captions (Ctrl+wheel)", each timing's `timing_tip` | `ui_next.qt_caption_tooltip`; any caption window state on hover |
| Caption window chips (languages, preset, timing), source tag, mic, usage ring, line save/copy | name, strip label | the chip's name (for example "Languages: Detect → French"), "{app} - {note}", "Show my speech here: on/off", `meter_text`, "Save caption", "Copy caption" | caption window states |
| Caption window pace rows | name | "Them: {n} words a minute, average {m}" | caption window pace states |
| Joined window strip buttons | name, strip label | as the caption window's | `ui_next.joined_*` |
| Caption window settings dropdown rows (from actions) | description box | the action's help when it isn't just its words (for example word links, lock) | caption window settings popover states |
| Settings dropdown: "Show my speech here" row | description box | `mic_button_tip` | caption window settings popover |
| Settings dropdown: source app list | item help | "Captioning starts when {app} plays sound - its first seconds can be missed" (an app not playing yet) | `ui_next.*apps*` popover states |
| Settings dropdown: second language | ⓘ | `second_tip`: "{language} is this window's language, so those lines aren't translated. …" | languages popover states |
| Timing dropdown rows (caption mode) | description box | `timing_tip` in full, with the preset's recommendation first | `ui_next.qt_timing_tooltip`, `ui_next.help_timing_described`, `_mirrored`, bar timing states |
| Preset dropdown: Readings | description box | "Pinyin, Jyutping or a respelling over the words" | `ui_next.help_readings_described`, preset dropdown states |
| Transcript timing menu | description box | `timing_tip` | transcript states |
| Transcript "Say it" menu: a side with no voice | description box | `no_voice_steps` | transcript selection states |
| Transcript strip: A-, A+, timing and language chips, tag | name | "Smaller text (Ctrl+wheel)", "Bigger text (Ctrl+wheel)", "Caption timing - for every window", "Translate into: {language}" / "Original only - no translation", "{app} - shows my speech" | transcript states |
| Settings rows with a tip and no line under them (a transcript's rail, the caption window's Look) | ⓘ beside the title | each row's line, for example "The first update waits for a second of speech.", the Names and slang examples, Lab's "Line by line: …" | `ui_next.panel_look_rail`, `ui_next.help_info`, `_mirrored`, timing and languages panels, lab panel |
| Look: the tone sliders, Around the letters | ⓘ beside the title | each slider's explanation; "What's drawn around captions' letters, …" | Settings > Captions > Look states |
| Look: thickness slider | name | the step's name ("Semibold") | Look states |
| Look: colour presets and recommended looks | description box beside the tiles | `preset_tip`, `look_tip`, "Your own colours, from {preset}." | `ui_next.looks_tiles_*`, Look states |
| Look: Reset card | ⓘ | "Colours, panel, font, word links and fading. To move the windows back, use Reset positions on Home." | Look states |
| Home: app rows' colour swatch, language chip, mic | name | "Colour", "Translate into", "Your speech shows in this window - click to stop" / "Show my speech in this window" | `ui_next.picker_*`, `ui_next.home*` |
| Home: Join windows | ⓘ | "Each caption window back at its own place" / "The caption windows as one, a column each" / "With two apps or more" | home states |
| Learning: switch main language, stop learning | ⓘ | "Takes effect when Polyglotic next starts", "Keeps its words; delete them on Account" | learning states |
| Learning: recorded words line, a pack's line | ⓘ | the recordings' and pack's credits | learning states |
| Presets card: New preset, Save as new when full | ⓘ | "The captions as they are now, as a preset of your own", "Five of your own at most: delete one first" | Settings > Presets states |
| Words: a category's colour, Delete | name, ⓘ | "Choose colour", "Delete this category and remove its saved words" | `ui_next.words_*` |
| Words: table cells | item help | "Open dictionary", a cut-off meaning in full, "Change status" / "Estimated from your level. Choose a status to change it.", "Move to another category", "Remove from saved words" | `ui_next.words_*` |
| Settings > Language: Machine draft | ⓘ | "No native speaker has checked the app's text in this language yet." | settings states for a draft language |
| Caption set-up card: Use as my default | ⓘ | "Use these choices for new caption windows and skip this card" | first window set-up states |
| Selection card: Say it, a side with no voice | ⓘ | `no_voice_steps` | selection states |
| Sound card: the mic level meter | name | "Your microphone's level now" / "Your mic's level, shown while your speech is captioned" | sound card states |

## Dropped or moved

Each line kept its text for a screen reader (`accessibleDescription`) unless it repeated the visible words.

| Where | Was (native tooltip) | Verdict |
|---|---|---|
| Every Settings row with its line under it | the line again | dropped: it repeated the line |
| Caption window captions (rows and labels) | the caption's own text | dropped: repeats |
| Back to live pill (caption window, transcript) | "Back to the newest captions ({key})" | dropped, screen reader keeps it: the pill says it |
| Home: Captions, Stop, Lock all, Hide all, an Add row and its Caption button, Add an app, Pick apps | hotkeys and explanations on labelled buttons and a whole row | dropped, screen reader keeps it |
| Home: app name | "Rename" | dropped (Codex round 1) |
| Hotkeys: Clear, Reset all; Lab: Reset the Lab; presets: Restore defaults; Settings: dictation key Reset, Match | explanations on labelled buttons | dropped, screen reader keeps it |
| Settings dropdown: Source chip | "The app this window captions - pick another here" | dropped, screen reader keeps it: "Source" says it |
| Lookup card, whole card | "Translated by a machine, not yet checked by a person" | dropped, screen reader keeps it: "Machine-made" shows where it applies |
| Learning: Undo, the custom size field | "Back to: {level}", its range | dropped, screen reader keeps it / the placeholder says it |
| Unlock pill | "Unlock every caption window" | dropped, screen reader keeps it |
| Page buttons (Privacy notice, Terms, status page…) | "Opens in your browser" | dropped |
| Settings timing choices | the selected timing's sentence | dropped: the sentence under them says it |
| Timing dropdown rows | a dim line under each name, which was cut off ("Each sentence once, finished: nothing") | moved into the box beside the dropdown, in full |
| Settings dropdown: languages and spoken language | long tooltips | moved to visible notes (Codex round 2) |
| Text buttons made from actions (Pause, Quit, Want to help, feedback) | Qt's copy of the action's words | cleared: they repeated the button |

## Not covered

- The tray icon's own tooltip (`QSystemTrayIcon`) is drawn by the operating system and stays.
- The tray menu's explanations (`ui/app.py`) are set on its actions, but Qt never shows them, because the tray menu doesn't show tooltips. A described tray menu would show them. That is proposed as a follow-up.
