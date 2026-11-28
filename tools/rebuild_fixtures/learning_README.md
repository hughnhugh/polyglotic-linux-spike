# Learning rebuild fixtures

These files freeze the Python desktop app's learning contracts for the Rust S3 rebuild, and are the net under any change to the learning store (933's learning-1). All text and IDs are public/common or invented for this corpus; the recorder never reads a user profile.

Re-record from the repository root with:

```console
uv run python -m tools.rebuild_fixtures.record
uv run python -m tools.rebuild_fixtures.record --check
uv run pytest tests/test_learning_rebuild_fixtures.py tests/test_learning_ladder.py tests/test_learning_recount.py
```

- `cards-view.json` records the real lookup card view model (including entry IDs, ordered readings and meanings, parts, display limits, counterparts and Back state).
- `cards.json` is the normalized card payload for two words in Mandarin, English, Japanese and Vietnamese.
- `dictionaries/` contains cut-down files written by the production dictionary writer and their credits.
- `profile-v11.sqlite` is the production v11 SQLite profile; `profile-v11.json` is its portable normalized snapshot, and `profile-v11-level.json` the level's copy beside it (decision 0048).
- `words-view-*.json` records the ordered Words data for each language.
- `line-words.json` records an invented line in each language: its words as the dictionary splits it, and its saved, new and deck words over the profile. Spans are zero-based, half-open Unicode code points; each line starts with a character outside the Basic Multilingual Plane, so a span counted in UTF-16 differs.
- `anki.csv` and `anki-apkg-notes.json` record the CSV and normalized notes passed to the real `.apkg` writer.
- `replayed-sessions.json` replays two sessions through the real exposure counting: two sources interleaved (the PC's video and the learner's mic), with a join, a replacement and withdrawals. The second is at 13:30 UTC, when the learner's day (Melbourne's, fixed at UTC+11) is the next: `first_heard` and the daily rows follow the UTC day, `last_heard` and `days_heard` the learner's.
- `from-server.json` applies statuses, saves and unsaves from the server to the profile, one exchange at a time: the latest `at` wins, and the learner's own status wins a tie. It is the learning side of sync, not the wire's.
- `knowledge-200.json` records `Knowledge.of()` for 200 entries spanning explicit and frequency-line answers.
- `ladder/` is the store's ladder: `vNN.sql` is a store at schema version NN, made by the app's first NN migrations and seeded in every table, with rows the app can't read; `vNN.json` is what today's app makes of it - what it reads, every row the file then holds (by SQL alone) and the level's copy. `started-again.json` is a store started again beside the level's copy.

The checked-in files are golden data: do not hand-edit them. The regression test records into a temporary directory and compares every byte, except that a `.sqlite` file is compared by its contents: SQLite stamps its own version in the file's header, which differs between Linux and Windows. `.gitattributes` keeps every byte as recorded, line endings included.
