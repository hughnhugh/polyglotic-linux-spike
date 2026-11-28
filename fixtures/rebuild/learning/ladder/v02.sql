PRAGMA user_version = 2;
CREATE TABLE level (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            scheme TEXT NOT NULL,
            midpoint REAL NOT NULL
        );
CREATE TABLE statuses (
            entry_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            source TEXT NOT NULL,
            at TEXT NOT NULL
        ) WITHOUT ROWID;
CREATE TABLE categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            color TEXT NOT NULL,
            position INTEGER NOT NULL
        ) WITHOUT ROWID;
CREATE TABLE saved_words (
            entry_id TEXT PRIMARY KEY,
            headword TEXT NOT NULL,
            traditional TEXT NOT NULL,
            reading TEXT NOT NULL,
            meaning TEXT NOT NULL,
            category_id TEXT NOT NULL REFERENCES categories (id) ON DELETE CASCADE,
            source_sentence TEXT NOT NULL,
            source_translation TEXT NOT NULL,
            saved_at TEXT NOT NULL
        ) WITHOUT ROWID;
CREATE TABLE exposures (
            entry_id TEXT PRIMARY KEY,
            heard INTEGER NOT NULL,
            heard_by_you INTEGER NOT NULL,
            heard_in_deck INTEGER NOT NULL
        ) WITHOUT ROWID;
CREATE TABLE daily_exposures (
            day TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY (day, entry_id)
        ) WITHOUT ROWID;
CREATE TABLE deck_words (
            entry_id TEXT PRIMARY KEY,
            headword TEXT NOT NULL,
            traditional TEXT NOT NULL,
            reading TEXT NOT NULL,
            meaning TEXT NOT NULL,
            sentence TEXT NOT NULL,
            translation TEXT NOT NULL,
            learned_at TEXT NOT NULL
        ) WITHOUT ROWID;
CREATE TABLE anki_exports (
            entry_id TEXT PRIMARY KEY,
            exported_at TEXT NOT NULL
        ) WITHOUT ROWID;
INSERT INTO "level" ("id", "scheme", "midpoint") VALUES (1, 'hsk-2025', 2.5);
INSERT INTO "statuses" ("entry_id", "status", "source", "at") VALUES ('fixture:bad:status', 'maybe', 'learner', '2026-10-01T09:00:00+00:00');
INSERT INTO "statuses" ("entry_id", "status", "source", "at") VALUES ('fixture:en:hello', 'ignored', 'imported', '2026-10-04T12:00:00+00:00');
INSERT INTO "statuses" ("entry_id", "status", "source", "at") VALUES ('fixture:zh:cha', 'learning', 'learner', '2026-10-20T18:45:30.250000+00:00');
INSERT INTO "statuses" ("entry_id", "status", "source", "at") VALUES ('fixture:zh:ni', 'known', 'learner', '2026-10-01T09:00:00+00:00');
INSERT INTO "statuses" ("entry_id", "status", "source", "at") VALUES ('fixture:zh:shui', 'new', 'estimated', '2026-10-03T07:15:00+00:00');
INSERT INTO "categories" ("id", "name", "color", "position") VALUES ('food', 'Food and drink', '#c0563b', 1);
INSERT INTO "categories" ("id", "name", "color", "position") VALUES ('garbled', 'Garbled', '#000000', 'first');
INSERT INTO "categories" ("id", "name", "color", "position") VALUES ('interesting', 'Interesting', '#2f9e8f', 0);
INSERT INTO "saved_words" ("entry_id", "headword", "traditional", "reading", "meaning", "category_id", "source_sentence", "source_translation", "saved_at") VALUES ('fixture:bad:saved', '水', '水', 'shuǐ', 'water', 'food', 'Fixture line: 水。', 'Fixture line: water.', 'last Tuesday');
INSERT INTO "saved_words" ("entry_id", "headword", "traditional", "reading", "meaning", "category_id", "source_sentence", "source_translation", "saved_at") VALUES ('fixture:zh:cha', '茶', '茶', 'chá', 'tea', 'food', 'Fixture line: 我喝茶。', 'Fixture line: I drink tea.', '2026-10-20T18:45:30.250000+00:00');
INSERT INTO "saved_words" ("entry_id", "headword", "traditional", "reading", "meaning", "category_id", "source_sentence", "source_translation", "saved_at") VALUES ('fixture:zh:ni', '你', '你', 'nǐ', 'you', 'interesting', 'Fixture line: 你好吗？', 'Fixture line: how are you?', '2026-10-01T09:00:00+00:00');
INSERT INTO "exposures" ("entry_id", "heard", "heard_by_you", "heard_in_deck") VALUES ('fixture:bad:exposures', 'lots', 0, 0);
INSERT INTO "exposures" ("entry_id", "heard", "heard_by_you", "heard_in_deck") VALUES ('fixture:en:hello', 0, 2, 0);
INSERT INTO "exposures" ("entry_id", "heard", "heard_by_you", "heard_in_deck") VALUES ('fixture:zh:cha', 4, 0, 2);
INSERT INTO "exposures" ("entry_id", "heard", "heard_by_you", "heard_in_deck") VALUES ('fixture:zh:ni', 9, 1, 0);
INSERT INTO "daily_exposures" ("day", "entry_id", "count") VALUES ('2026-10-01', 'fixture:zh:ni', 4);
INSERT INTO "daily_exposures" ("day", "entry_id", "count") VALUES ('2026-10-02', 'fixture:bad:daily', 'two');
INSERT INTO "daily_exposures" ("day", "entry_id", "count") VALUES ('2026-10-09', 'fixture:zh:ni', 2);
INSERT INTO "daily_exposures" ("day", "entry_id", "count") VALUES ('2026-10-20', 'fixture:zh:ni', 3);
INSERT INTO "daily_exposures" ("day", "entry_id", "count") VALUES ('2026-10-21', 'fixture:zh:ni', 0);
INSERT INTO "deck_words" ("entry_id", "headword", "traditional", "reading", "meaning", "sentence", "translation", "learned_at") VALUES ('fixture:bad:deck', '水', '水', 'shuǐ', 'water', 'Fixture line: 水。', 'Fixture line: water.', X'00ff');
INSERT INTO "deck_words" ("entry_id", "headword", "traditional", "reading", "meaning", "sentence", "translation", "learned_at") VALUES ('fixture:zh:cha', '茶', '茶', 'chá', 'tea', 'Fixture line: 一杯茶。', 'Fixture line: a cup of tea.', '2026-10-20T18:45:30.250000+00:00');
INSERT INTO "deck_words" ("entry_id", "headword", "traditional", "reading", "meaning", "sentence", "translation", "learned_at") VALUES ('fixture:zh:ni', '你', '你', 'nǐ', 'you', 'Fixture line: 你好。', 'Fixture line: hello.', '2026-10-01T09:00:00+00:00');
INSERT INTO "anki_exports" ("entry_id", "exported_at") VALUES ('fixture:bad:anki', 'never');
INSERT INTO "anki_exports" ("entry_id", "exported_at") VALUES ('fixture:zh:cha', '2026-10-06T10:00:00+00:00');
INSERT INTO "anki_exports" ("entry_id", "exported_at") VALUES ('fixture:zh:ni', '2026-10-05T10:00:00+00:00');
