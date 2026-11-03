CREATE TABLE source (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    base_url  TEXT NOT NULL,
    language  TEXT NOT NULL CHECK (language IN ('ja', 'zh'))
);

INSERT INTO source (name, base_url, language) VALUES
    ('syosetu', 'https://ncode.syosetu.com', 'ja'),
    ('jjwxc',   'https://www.jjwxc.net',     'zh');

CREATE TABLE novel (
    id           INTEGER PRIMARY KEY,
    source_id    INTEGER NOT NULL REFERENCES source (id),
    external_id  TEXT NOT NULL,
    title        TEXT NOT NULL,
    author       TEXT,
    url          TEXT NOT NULL,
    genre        TEXT,
    synopsis     TEXT,
    length_chars INTEGER,
    chapter_count INTEGER,
    status       TEXT CHECK (status IN ('ongoing', 'completed', 'hiatus')),
    fetched_at   REAL,
    UNIQUE (source_id, external_id)
);

CREATE TABLE cache_entry (
    url        TEXT PRIMARY KEY,
    host       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    status     INTEGER NOT NULL,
    fetched_at REAL NOT NULL,
    path       TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    bytes      INTEGER NOT NULL
);
CREATE INDEX cache_entry_host ON cache_entry (host, kind);

CREATE TABLE fetch_log (
    id      INTEGER PRIMARY KEY,
    ts      REAL NOT NULL,
    host    TEXT NOT NULL,
    url     TEXT NOT NULL,
    status  INTEGER,
    ms      INTEGER,
    outcome TEXT NOT NULL
);
CREATE INDEX fetch_log_host_ts ON fetch_log (host, ts);
