-- Dictionary data, domains and short excerpts for the learner model (milestone 3).
-- All of it can be rebuilt: dictionaries are loaded from files in data/dicts/, domain
-- tags are recomputed by `wn analyse --domains`, excerpts by `wn syosetu excerpts`.

ALTER TABLE lemma ADD COLUMN gloss TEXT;
ALTER TABLE lemma ADD COLUMN jmdict_id INTEGER;
-- Space-separated JMdict field and usage tags of the matched entry, e.g. "chem col".
ALTER TABLE lemma ADD COLUMN tags TEXT;

-- Every written form and reading JMdict knows, so a made-up test word can be checked.
CREATE TABLE dict_form (
    form     TEXT NOT NULL,
    entry_id INTEGER NOT NULL,
    PRIMARY KEY (form, entry_id)
);

CREATE TABLE domain (
    key     TEXT PRIMARY KEY,
    name_en TEXT NOT NULL,
    name_ja TEXT NOT NULL,
    position INTEGER NOT NULL
);

CREATE TABLE lemma_domain (
    lemma_id INTEGER NOT NULL REFERENCES lemma (id) ON DELETE CASCADE,
    domain   TEXT NOT NULL REFERENCES domain (key),
    weight   REAL NOT NULL CHECK (weight > 0 AND weight <= 1),
    source   TEXT NOT NULL CHECK (source IN ('dictionary', 'learned')),
    PRIMARY KEY (lemma_id, domain)
);
CREATE INDEX lemma_domain_domain ON lemma_domain (domain);

-- Short passages for the placement test. They stay in this local file only.
-- ``tokens`` is JSON: [[surface, lemma_id or null, pos], ...] in reading order.
CREATE TABLE excerpt (
    id         INTEGER PRIMARY KEY,
    novel_id   INTEGER NOT NULL REFERENCES novel (id) ON DELETE CASCADE,
    chapter_no INTEGER NOT NULL,
    text       TEXT NOT NULL,
    chars      INTEGER NOT NULL,
    tokens     TEXT NOT NULL,
    UNIQUE (novel_id, text)
);
CREATE INDEX excerpt_novel ON excerpt (novel_id);

CREATE TABLE jlpt_word (
    lemma   TEXT NOT NULL,
    reading TEXT NOT NULL DEFAULT '',
    level   INTEGER NOT NULL CHECK (level BETWEEN 1 AND 5),
    PRIMARY KEY (lemma, reading)
);

CREATE TABLE dict_meta (
    name       TEXT PRIMARY KEY,
    version    TEXT,
    source     TEXT,
    sha256     TEXT,
    entries    INTEGER,
    loaded_at  REAL NOT NULL
);

INSERT INTO domain (key, name_en, name_ja, position) VALUES
    ('fantasy',  'Fantasy and magic',            'ファンタジー・魔法',  1),
    ('games',    'Games and status screens',     'ゲーム・ステータス',  2),
    ('court',    'Nobility and court',           '貴族・宮廷',          3),
    ('combat',   'Combat and military',          '戦闘・軍事',          4),
    ('romance',  'Romance and feelings',         '恋愛・感情',          5),
    ('school',   'School life',                  '学園生活',            6),
    ('speech',   'Everyday and internet speech', '日常・くだけた話し言葉', 7),
    ('crime',    'Crime, law and mystery',       '犯罪・法律・推理',    8),
    ('medicine', 'Body and medicine',            '身体・医療',          9),
    ('science',  'Science and technology',       '科学・技術',         10),
    ('money',    'Money and business',           '金銭・商売',         11),
    ('formal',   'Formal and literary register', '改まった・文語的な言葉', 12);
