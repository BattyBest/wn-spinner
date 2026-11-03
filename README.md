# wn-spinner

A local-first companion for reading webnovels in Japanese and Chinese. It collects
novel metadata and short samples, scores each novel against your own vocabulary,
recommends ones at the right difficulty, and sends you to the source site to read.

Everything runs on your machine. There is no account and no cloud database: your data
lives in two SQLite files in `data/`, and the original sites are where you read.

**Status:** early development. Milestones 1 to 4 are in place: a polite page collector,
the databases, a local API, and Japanese and Chinese support end to end. `wn syosetu run` and
`wn jjwxc run` collect novels and analyse their vocabulary. A placement test measures your own
vocabulary, overall and by domain (fantasy, money, medicine and so on), and every novel is then
scored against *you*: a predicted coverage, a band from Comfortable to Too hard, and a "Best for
me" ordering. A switch in the app moves between 日本語 and 中文; each language has its own test,
profile and word list.

Sources: [Syosetu](https://syosetu.com/) (Japanese) and [jjwxc](https://www.jjwxc.net/)
(Chinese, Simplified).

## Setup

You need Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22 and pnpm 10.
With Nix, `nix-shell` provides all of them.

```sh
make setup   # install Python and frontend dependencies
make run     # build the UI and serve everything at http://localhost:8000
```

For development, `make dev` runs the API on `:8000` and the Vite dev server on
`:5173`, which proxies `/api` to the API and reloads on changes.

Other targets: `make test`, `make lint`, `make fmt`, `make build`.

## The `wn` command

```sh
uv run wn robots ncode.syosetu.com        # what the site's robots.txt allows, and our delay
uv run wn fetch <url> --dry-run           # show what a fetch would do, send nothing
uv run wn fetch <url>                     # fetch politely; the second call hits the cache
uv run wn cache stats                     # cached pages per host
uv run wn cache purge --kind chapter      # delete cached chapter text
uv run wn serve                           # API and UI on :8000
```

### Collecting Syosetu

```sh
uv run wn syosetu run --limit 200         # rankings, metadata, then chapters; asks before the long part
uv run wn syosetu sample --dry-run        # the plan for pending novels, nothing sent
uv run wn syosetu deepen                  # top novels up to 20,000 characters, opened ones first
uv run wn analyse                         # recompute word ranks and statistics from stored counts
```

`run` saves rankings and metadata first, so Discover fills within seconds, then reads chapters
until each novel has about 10,000 characters and analyses each one as it arrives. It can be
stopped and started again at any point. A first run of 200 novels is a few hundred page
requests at Syosetu's own 1 s delay. After that, only new or updated novels cost requests.

### Collecting jjwxc (Chinese)

```sh
uv run wn jjwxc run --limit 200           # rankings, book pages, then free chapters
uv run wn jjwxc sample --dry-run          # the plan for pending novels, nothing sent
uv run wn jjwxc deepen                    # top novels up to 20,000 characters, opened ones first
uv run wn analyse --lang zh               # recompute word ranks and statistics (default: both)
```

The candidates are the union of three of jjwxc's ranking lists (monthly, quarterly and new
authors), 200 novels by default. Only **free** chapters are ever requested: the VIP chapters, the
login pages and `my.jjwxc.net` are never touched, and a novel with no free chapters is simply
skipped. Words are segmented with [jieba](https://github.com/fxsjy/jieba). Books that the author
marks as for adult readers (18岁以上) are kept and scored but labelled **Mature** and hidden
unless you tick "Show mature books"; R18 works on Syosetu are still never requested.

### Your level and recommendations

```sh
uv run wn dict fetch                      # JMdict glosses and JLPT lists into data/dicts/ (once)
uv run wn dict fetch --lang zh            # CC-CEDICT glosses and pinyin, and the HSK 3.0 lists
uv run wn dict load --jmdict FILE --jlpt FILE   # or load files you downloaded yourself
uv run wn dict load --cedict FILE --hsk FILE    # (CC-CEDICT .zip/.gz/text, HSK complete.json)
uv run wn analyse --domains               # tag words with domains (after each collection run)
uv run wn syosetu excerpts                # keep short passages for the test (one page per novel)
uv run wn jjwxc excerpts                  # the same for Chinese
uv run wn dict status                     # what is loaded
uv run wn model bench                      # score the learner model on simulated learners
uv run wn model check                      # hold out your own answers and marks, old model vs new
```

Then open the Test screen. It needs a catalog of a couple of hundred novels (a frequency list
built from five would make the test meaningless) and JMdict loaded (meaning checks and made-up
words need it). Your answers live in `profile.db`; the model is refitted from them after every
answer.

Data lives in `./data` by default; set `WN_DATA_DIR` to put it elsewhere.

## Being a good citizen

The collector checks `robots.txt` before any crawl and stops on a disallow, sends an
honest User-Agent, spaces the start of each request to a host by the host's `Crawl-delay`
(0.5 s when it says nothing), measured from start to start, so a slow response does not add to
it. Up to 10 requests to one host may be in flight at once, but never started closer together than
that delay. It also caps requests per day, backs off on errors (holding the whole host), and
switches a host off for the day on repeated failures or a bot-check page. It never tries to get around a challenge. Chapter text is
only used for analysis and then deleted, and reading always happens on the source site. Only word
counts and statistics are kept, and Syosetu's adult (R18) works are never requested.

## Data and licences

JMdict is the work of the [EDRDG](https://www.edrdg.org/) and is used under
[CC BY-SA 4.0](https://www.edrdg.org/edrdg/licence.html); the JLPT word lists are community
lists compiled by Jonathan Waller (CC BY). For Chinese, [CC-CEDICT](https://cc-cedict.org/) is
used under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) and the HSK 3.0 lists
come from the MIT-licensed [complete-hsk-vocabulary](https://github.com/drkameleon/complete-hsk-vocabulary)
project. All are downloaded onto your machine by `wn dict fetch`, kept in `data/dicts/` and never
committed to this repository. jieba is MIT-licensed. HSK level 7 stands for HSK 7–9.

The placement test shows short excerpts (80 to 300 characters) of the novels it collected. They
are stored only in your local `data/catalog.db`, which is git-ignored, and are never sent anywhere.

## Licence

[MIT](LICENSE)
