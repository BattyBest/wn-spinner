# wn-spinner

A local-first companion for reading webnovels in Japanese and Chinese. It collects
novel metadata and short samples, scores each novel against your own vocabulary,
recommends ones at the right difficulty, and sends you to the source site to read.

Everything runs on your machine. There is no account and no cloud database: your data
lives in two SQLite files in `data/`, and the original sites are where you read.

**Status:** early development. Milestone 1 (foundations) is in place: a polite page
collector, the databases, a local API and a placeholder UI. No novels are collected yet.

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

Data lives in `./data` by default; set `WN_DATA_DIR` to put it elsewhere.

## Being a good citizen

The collector checks `robots.txt` before any crawl and stops on a disallow, sends an
honest User-Agent, keeps one connection per host with a minimum delay between requests,
caps requests per day, backs off on errors, and switches a host off for the day on repeated
failures or a bot-check page. It never tries to get around a challenge. Chapter text is
only used for analysis and then deleted, and reading always happens on the source site.

## Licence

[MIT](LICENSE)
