# 0307 Steady's older cards scroll flat

- **Status:** accepted
- **Date:** 2026-11-29
- **Decided by:** the founder, 2026-11-29 (~03:00, polyglotic-hq project
  1070): "Can you also remove this weird 3d flip thing on older captions
  in calm and steady, feel free to strip this out in the refactor too".
  Built by project 1070's part 2; Claude reviews before merge.
- **Replaces:** decision 0260's line "Older cards turn away on a drum",
  and 0282's item 7 as far as it concerns the drum. The rest of 0260 (the
  cards, their one motion, the deck between the playout and the view) and
  0282 (Video's depth) stand.

## Situation

In Steady and Calm, cards above the lower 55 % of the window turned away
on a drum (`views.cards.drum`): closer together, squashed, fainter, and
gone before the top edge. The founder found it strange to read.

## Decision

- **Older cards scroll flat.** While the window follows the speech, every
  card is drawn whole, at its own height, one card's pitch above the next.
  A new card pushes the stack up in the one glide (`views.cards.Glide`).
  The oldest card leaves over the top, fading whole as it passes the top
  edge, the toolbar or a question (`_cover`), as it did under them before.
- **The cards stay** as 0260 has them: they never change shape, each
  card's place is kept, and translations are kept in their room.
- **The drum is deleted, not switched off:** `drum`, `drum_room`,
  `FLAT_SHARE`, `FAR_INK`, `GONE_AT`, `SMEAR`, `FLAT_ENOUGH`, the paint
  branch that squashed a card, and their tests. The canvas's `turning` list
  becomes `fading` (cards drawn but not pointed at), without a scale.
- **Video's depth is untouched** (0282): Video paints its own way.
- **Out of reading:** the card a new card takes out of reading is now the
  oldest card that fits whole in the window, where before it was the
  oldest flat one (`CaptionWindow._leaving`).

## Why

- The founder asked for it in so many words. The drum showed more older
  cards, but squashed and faint ones. A flat list shows fewer, each one
  readable, which is what scrolling back already did.
- One way to show cards, live or scrolled back, is less code and fewer
  states to check.

## What would make us reverse it

Learners missing the older cards a flat window can't hold, or a stack
that feels too tall to follow.

## How we'd reverse it

Bring back `drum` and `drum_room` from git (they were pure functions),
the `_rolled` room in `_view_height` and `_positioned`, and the squash
branch in the live cards' paint. About a day, with its tests.
