ALTER TABLE novel ADD COLUMN keywords TEXT;
ALTER TABLE novel ADD COLUMN kind TEXT CHECK (kind IN ('serial', 'short'));
ALTER TABLE novel ADD COLUMN is_r15 INTEGER NOT NULL DEFAULT 0;
ALTER TABLE novel ADD COLUMN points INTEGER;
ALTER TABLE novel ADD COLUMN bookmarks INTEGER;
ALTER TABLE novel ADD COLUMN site_dialogue_pct INTEGER;
ALTER TABLE novel ADD COLUMN first_up TEXT;
ALTER TABLE novel ADD COLUMN last_up TEXT;
-- The site's last-update stamp seen when the novel was last sampled; a refresh skips
-- novels where it has not changed.
ALTER TABLE novel ADD COLUMN sampled_up TEXT;
ALTER TABLE novel ADD COLUMN opened_at REAL;
ALTER TABLE novel ADD COLUMN raw TEXT;

-- Why a novel is in the catalog, and a popularity signal.
CREATE TABLE ranking (
    novel_id INTEGER NOT NULL REFERENCES novel (id) ON DELETE CASCADE,
    list     TEXT NOT NULL CHECK (list IN ('daily', 'weekly', 'monthly', 'quarterly')),
    date     TEXT NOT NULL,
    rank     INTEGER NOT NULL,
    points   INTEGER,
    PRIMARY KEY (novel_id, list, date)
);

-- Which chapters were read. No text is stored here, only what analysis measured.
CREATE TABLE sample (
    novel_id      INTEGER NOT NULL REFERENCES novel (id) ON DELETE CASCADE,
    chapter_no    INTEGER NOT NULL,
    chars         INTEGER NOT NULL,
    sentences     INTEGER,
    kanji_chars   INTEGER,
    dialogue_chars INTEGER,
    fetched_at    REAL NOT NULL,
    analysed_at   REAL,
    PRIMARY KEY (novel_id, chapter_no)
);

-- One row per distinct word across the catalog.
CREATE TABLE lemma (
    id           INTEGER PRIMARY KEY,
    language     TEXT NOT NULL CHECK (language IN ('ja', 'zh')),
    lemma        TEXT NOT NULL,
    pos          TEXT NOT NULL,
    reading      TEXT,
    is_function  INTEGER NOT NULL DEFAULT 0,
    oov          INTEGER NOT NULL DEFAULT 0,
    corpus_count INTEGER NOT NULL DEFAULT 0,
    corpus_rank  INTEGER,
    UNIQUE (language, lemma, pos)
);

CREATE TABLE novel_lemma (
    novel_id INTEGER NOT NULL REFERENCES novel (id) ON DELETE CASCADE,
    lemma_id INTEGER NOT NULL REFERENCES lemma (id),
    count    INTEGER NOT NULL,
    is_name  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (novel_id, lemma_id)
);
CREATE INDEX novel_lemma_lemma ON novel_lemma (lemma_id);

CREATE TABLE novel_stats (
    novel_id         INTEGER PRIMARY KEY REFERENCES novel (id) ON DELETE CASCADE,
    sample_chars     INTEGER NOT NULL,
    tokens           INTEGER NOT NULL,
    unique_lemmas    INTEGER NOT NULL,
    cover_1k         REAL,
    cover_2k         REAL,
    cover_3k         REAL,
    cover_5k         REAL,
    cover_10k        REAL,
    sentence_len     REAL,
    kanji_pct        REAL,
    dialogue_pct     REAL,
    rare_load        INTEGER,
    analyser_version INTEGER NOT NULL,
    analysed_at      REAL NOT NULL
);
