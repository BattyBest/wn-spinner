-- The learner model and the evidence it is fitted from (milestone 3).
-- Words are referred to by language, lemma and part of speech, never by catalog row id,
-- so this file stays valid if catalog.db is rebuilt.

-- One row per language: the latest fit. It can always be refitted from ``answer``.
CREATE TABLE model (
    language   TEXT PRIMARY KEY CHECK (language IN ('ja', 'zh')),
    version    INTEGER NOT NULL,
    params     TEXT NOT NULL,   -- JSON: {"theta": [mean, sd], "domains": {key: [mean, sd]}}
    guess_rate REAL NOT NULL,
    answers    INTEGER NOT NULL,
    fitted_at  REAL NOT NULL
);

CREATE TABLE test_session (
    id         INTEGER PRIMARY KEY,
    language   TEXT NOT NULL CHECK (language IN ('ja', 'zh')),
    kind       TEXT NOT NULL CHECK (kind IN ('full', 'quick')),
    state      TEXT NOT NULL,   -- JSON: asked items, the pending item, counters
    started_at REAL NOT NULL,
    finished_at REAL
);

CREATE TABLE answer (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES test_session (id),
    language   TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('word', 'fake', 'meaning', 'tap', 'untapped', 'mark')),
    lemma      TEXT,
    pos        TEXT,
    known      INTEGER NOT NULL CHECK (known IN (0, 1)),  -- what the answer says
    weight     REAL NOT NULL,
    at         REAL NOT NULL
);
CREATE INDEX answer_language ON answer (language, id);

-- Passage ratings and cloze answers, kept beside the coverage predicted at the time.
CREATE TABLE passage_result (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES test_session (id),
    excerpt_id INTEGER NOT NULL,
    predicted  REAL NOT NULL,
    rating     TEXT NOT NULL CHECK (rating IN ('almost_all', 'most', 'gist', 'lost')),
    cloze_ok   INTEGER,
    at         REAL NOT NULL
);

CREATE TABLE word_status (
    language TEXT NOT NULL,
    lemma    TEXT NOT NULL,
    pos      TEXT NOT NULL,
    known    INTEGER NOT NULL CHECK (known IN (0, 1)),
    at       REAL NOT NULL,
    PRIMARY KEY (language, lemma, pos)
);

CREATE TABLE domain_fix (
    language TEXT NOT NULL,
    lemma    TEXT NOT NULL,
    pos      TEXT NOT NULL,
    domain   TEXT NOT NULL,
    action   TEXT NOT NULL CHECK (action IN ('add', 'remove')),
    PRIMARY KEY (language, lemma, pos, domain)
);

CREATE TABLE novel_feedback (
    id        INTEGER PRIMARY KEY,
    source    TEXT NOT NULL,
    novel     TEXT NOT NULL,     -- the source's own id, e.g. an ncode
    title     TEXT,
    felt      TEXT NOT NULL CHECK (felt IN ('easier', 'right', 'harder')),
    predicted REAL,
    note      TEXT,
    at        REAL NOT NULL
);
