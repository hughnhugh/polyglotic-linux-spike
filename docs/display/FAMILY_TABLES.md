# Wrapping and movement family decisions

This companion to the generated [display rulebook](RULEBOOK.md) gives the
requested family views. “Where decided” names the product choices recorded by
each rule; the rulebook has their full paths, tests, history and pictures.

## Wrapping and line breaks

| Id | Statement | Where decided | Conflicts | Recommendation and reason |
|---|---|---|---|---|
| `wrapping.live-breaks-follow-the-newest-text` | A changing live caption is fitted again from its newest text; breaks already shown are not frozen. | `CaptionLayout._composed`; `Flow.compose` | `movement.words-never-fall` wins today, pulling a newly broken row over the first. | **Change:** adopt 827's frozen breaks so corrections stay in place and cannot conflict with words never falling. |
| `wrapping.every-row-is-a-single-line` | A caption carries on in new one-line rows; a row never wraps inside itself. | `_single_line_rows`; `CaptionLayout._flowed`; `CaptionLayout._lay_out`; `_laid_text` | The transcript still wraps a long row inside itself. | **Keep:** it holds throughout caption windows and Video; the planned transcript alignment should make it universal. |

## Movement

| Id | Statement | Where decided | Conflicts | Recommendation and reason |
|---|---|---|---|---|
| `movement.words-never-fall` | Text already on screen never moves down; shorter revisions leave a gap for later text to fill. | `row_tops`; `Canvas._place_rows`; `Canvas._follow_words`; `VideoFlow.advance` | Newest live breaks cause overlap; Video's own breaks still let words fall. | **Keep:** this is the founder's hard rule; freeze shown breaks and bring Video into line. |
| `movement.no-sideways-slide` | Rows do not travel sideways. | `Canvas._paint_panel` (every row drawn from the same left edge) | Video Scrolling deliberately pans a row too wide for its window. | **Keep:** the rejected slide-in was visibly worse; preserve only Video Scrolling's reading aid. |
| `movement.the-approved-glide` | Captions making room glide at no more than 300 px/s and do not jump. | `Glide.push`; `CaptionWindow._note_arrivals`; `Canvas._list_positions`; `CaptionWindow._settle_burst` | Words never fall wins after a rebreak; an over-height burst settles immediately. | **Keep:** it holds for ordinary panel and joined-window movement; the two explicit exceptions prevent overlap/falling and uncatchable lag. |
| `movement.a-burst-settles-at-once` | More captions than the window can follow are put in their resting places at once. | `CaptionWindow._note_arrivals`; `CaptionWindow._settle_burst` | It deliberately overrides the approved glide. | **Keep:** animating more than a window of travel would leave captions behind the speech. |
| `movement.a-new-row-waits-then-fades-in` | A new row waits for its place to clear, then fades in where it will stay. | `Canvas._reveal_wraps`; `CaptionWindow._note_arrivals` | With `movement.words-never-fall`: on the made-up rapid-revision stream a row held low can touch a new caption for a few frames (8 of 216 caption-window and 8 of 216 joined-window replays); words never fall wins. | **Keep:** waiting avoids both overlap and the rejected sideways entrance. |
