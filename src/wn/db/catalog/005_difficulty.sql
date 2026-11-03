-- A better difficulty for each word than its raw catalog rank (see learner/difficulty.py).
-- All three columns are rebuilt by `wn analyse` (difficulty) and `wn dict` (is_common).

-- JMdict marks an entry common when it has a news, ichi, spec or gai priority tag.
-- Null where the dictionary has no such flag (Chinese) or is not loaded.
ALTER TABLE lemma ADD COLUMN is_common INTEGER;
-- Estimated ln rank blended from the catalog rank and the level lists, and its uncertainty.
ALTER TABLE lemma ADD COLUMN difficulty REAL;
ALTER TABLE lemma ADD COLUMN difficulty_sd REAL;
