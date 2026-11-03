# wn-spinner

A local-first companion for reading webnovels in Japanese and Chinese. It collects
novel metadata and short samples, scores each novel against your own vocabulary,
recommends ones at the right difficulty, and sends you to the source site to read.

Everything runs on your machine. There is no account and no cloud database: your data
lives in two SQLite files in `data/`, and the original sites are where you read.

**Status:** early development. Milestones 1 and 2 are in place: a polite page collector,
the databases, a local API, and Japanese support end to end. `wn syosetu run` collects novels
from Syosetu, analyses their vocabulary and fills the Discover and Novel detail screens.
Scoring novels against *your* level (the learner model and placement test) comes next, and
Chinese after that.

Sources: [Syosetu](https://syosetu.com/) (Japanese) first, then
[jjwxc](https://www.jjwxc.net/) (Chinese).

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

Data lives in `./data` by default; set `WN_DATA_DIR` to put it elsewhere.

## Being a good citizen

The collector checks `robots.txt` before any crawl and stops on a disallow, sends an
honest User-Agent, keeps one connection per host and waits between requests for as long as
the host's `Crawl-delay` says (0.5 s when it says nothing), caps requests per day, backs off on errors, and switches a host off for the day on repeated
failures or a bot-check page. It never tries to get around a challenge. Chapter text is
only used for analysis and then deleted, and reading always happens on the source site. Only word
counts and statistics are kept, and adult (R18) works are never requested.

## Licence

[MIT](LICENSE)
