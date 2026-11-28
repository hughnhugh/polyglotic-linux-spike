# 0308 Steady's letters light with the speech

- **Status:** accepted
- **Date:** 2026-11-29
- **Decided by:** the founder, 2026-11-29 (~03:00, polyglotic-hq project
  1070): "Can you also make the word letters themselves establish smoothly
  too? like a clean mexican wave in line with the pace of the speech
  (basically smoothed out)". Built by project 1070's part 3; Claude
  reviews before merge. The rulebook's "Letters light with the speech"
  is marked keep from those words.
- **Builds on:** 0245 (the playout), 0228 (established text drawn as
  final), 0307 (older cards scroll flat).

## Situation

In Steady and Calm the playout shows a word at the moment it was said plus
a delay, and the whole word turned from the waiting grey to full ink at
once: a step every word, at the speaker's pace.

## Decision

- **The playout says how long a shown word took to say**
  (`CaptionUpdate.lighting`): from the server's word times where an update
  carries them, else until the next word's moment; never longer than the
  delay, and over by the time the next word is due (a word shown late
  lights sooner). The finished caption that the last word brings carries it
  too. It is the app's own; it is never sent.
- **A window lights a row's newly established letters one after another
  across that time** (`views.wave`): its letters and digits as they were
  said (each Chinese, Japanese or Korean character a letter), each space
  or mark with the letter before it. Each letter eases from the waiting ink
  to the full ink over `wave.fade` (0.16 s, 0.05-0.4): the front is two or
  three letters wide at the speaker's pace. A word shown before the last
  finished takes the rest of it along. A translation lights with the word
  that completes its clause; each joined column at its own speaker's pace.
- **Only the lines lighting are drawn for it:** the frame tick updates the
  rects of lines whose letters are still lighting, and stops when none is.
- **Reduced motion:** with the OS's setting on, no wave; whole words light
  as before.

## Why

- The founder asked for it. The playout already knows each word's spoken
  moment, so the front can follow the speech exactly: each letter begins at
  its spoken moment plus the delay, to within a frame (the rule's test).
- Drawing the front as per-letter colours at paint time (Qt's format
  ranges) needs no new layout, so a frame stays within its budget.

## What would make us reverse it

Learners finding the moving edge distracting, or frames over budget on the
reference PC while someone talks.

## How we'd reverse it

Return no wave from `Canvas._lit` (or set `wave.fade` and the lighting to
0): words light whole again. Deleting it is `views/wave.py`, the `lit`
argument of `CaptionLayout.paint`, `CaptionUpdate.lighting` and the
playout's `_lasts` and `_lighting`, with their tests: half a day.
