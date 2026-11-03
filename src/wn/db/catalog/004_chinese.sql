-- Chinese support (milestone 4): the level lists and dictionary forms become per language,
-- domains get Chinese names, and jjwxc's mature-reader advisory gets its own flag.

-- JLPT and HSK lists share one table. ``jlpt_word`` rows are Japanese; HSK level 7 stands
-- for HSK 7-9.
CREATE TABLE level_word (
    language TEXT NOT NULL CHECK (language IN ('ja', 'zh')),
    lemma    TEXT NOT NULL,
    reading  TEXT NOT NULL DEFAULT '',
    level    INTEGER NOT NULL CHECK (level BETWEEN 1 AND 7),
    PRIMARY KEY (language, lemma, reading)
);
INSERT INTO level_word (language, lemma, reading, level)
    SELECT 'ja', lemma, reading, level FROM jlpt_word;
DROP TABLE jlpt_word;

-- Every written form a dictionary knows, so a made-up test word can be checked.
CREATE TABLE dict_form_new (
    language TEXT NOT NULL CHECK (language IN ('ja', 'zh')),
    form     TEXT NOT NULL,
    entry_id INTEGER NOT NULL,
    PRIMARY KEY (language, form, entry_id)
);
INSERT INTO dict_form_new (language, form, entry_id)
    SELECT 'ja', form, entry_id FROM dict_form;
DROP TABLE dict_form;
ALTER TABLE dict_form_new RENAME TO dict_form;

-- The id of the matched dictionary entry (JMdict id, or CC-CEDICT line number).
ALTER TABLE lemma RENAME COLUMN jmdict_id TO dict_id;

ALTER TABLE domain ADD COLUMN name_zh TEXT NOT NULL DEFAULT '';
UPDATE domain SET name_zh = CASE key
    WHEN 'fantasy'  THEN '奇幻、玄幻与仙侠'
    WHEN 'games'    THEN '游戏与系统面板'
    WHEN 'court'    THEN '宫廷与世家'
    WHEN 'combat'   THEN '战斗与军事'
    WHEN 'romance'  THEN '爱情与情感'
    WHEN 'school'   THEN '校园生活'
    WHEN 'speech'   THEN '日常与网络用语'
    WHEN 'crime'    THEN '犯罪、法律与悬疑'
    WHEN 'medicine' THEN '身体与医疗'
    WHEN 'science'  THEN '科学与技术'
    WHEN 'money'    THEN '金钱与商业'
    WHEN 'formal'   THEN '书面语与文言'
END;

-- Share of tokens that are idioms (chengyu); Chinese only.
ALTER TABLE novel_stats ADD COLUMN idiom_rate REAL;

-- The author's mature-reader advisory on jjwxc. Shown as "Mature" and hidden by default.
ALTER TABLE novel ADD COLUMN is_mature INTEGER NOT NULL DEFAULT 0;
-- The site's own favourites count (jjwxc); null where the source has none.
ALTER TABLE novel ADD COLUMN favourites INTEGER;

-- jjwxc has no daily or weekly list; it has half-year, new-author and all-time ones.
CREATE TABLE ranking_new (
    novel_id INTEGER NOT NULL REFERENCES novel (id) ON DELETE CASCADE,
    list     TEXT NOT NULL CHECK (list IN
                 ('daily', 'weekly', 'monthly', 'quarterly', 'halfyear', 'newcomers', 'alltime')),
    date     TEXT NOT NULL,
    rank     INTEGER NOT NULL,
    points   INTEGER,
    PRIMARY KEY (novel_id, list, date)
);
INSERT INTO ranking_new (novel_id, list, date, rank, points)
    SELECT novel_id, list, date, rank, points FROM ranking;
DROP TABLE ranking;
ALTER TABLE ranking_new RENAME TO ranking;
