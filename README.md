# Competitor Content Intelligence

Collects public content from US life insurance agents and agencies (YouTube and Instagram),
labels each post (topic, format, hook, call to action), ranks posts by how much engagement they
earned, and shows the best content and the strongest competitors.

| Part | Stack |
|---|---|
| `backend/` | Python 3.13, FastAPI, SQLAlchemy 2, SQLite, uv |
| `frontend/` | React + TypeScript (Vite), Pico.css, pnpm |

Official APIs only (YouTube Data API, Instagram Graph API). Labeling uses the Gemini free tier,
with a rules fallback, so the app also runs with no Gemini key.

## Quick start

Prerequisites: Python 3.13 with [uv](https://docs.astral.sh/uv/), Node.js 22 with pnpm 10
(`corepack install -g pnpm@10`), and `make`.

```bash
make setup      # installs both sides, creates backend/.env, creates the database, seeds search terms
```

Then put your keys in `backend/.env` (see [Configuration](#configuration)) and fill the database:

```bash
make refresh DISCOVER=1   # find competitors, collect their posts, label, rank
make run                  # build the frontend and serve everything on http://localhost:8000
```

`make run` is the one-process demo: FastAPI serves the API under `/api` and the built frontend at
`/`. Interactive API docs are at http://localhost:8000/docs. Run `make help` to list every command.

A first full run takes a while: YouTube discovery spends about 3,000 of the 10,000 daily quota
units, each Instagram hashtag takes about 2 minutes, and Gemini labels 10 posts per request at
10 requests a minute. Every step can be run alone and is safe to repeat.

## Configuration

`backend/.env` (created from `backend/.env.example`; never committed). An empty key turns that
integration off.

| Variable | What it is for |
|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3 key. Without it nothing is collected from YouTube. |
| `META_GRAPH_VERSION`, `IG_USER_ID`, `IG_ACCESS_TOKEN` | Instagram: your own professional account and a token with `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`, `pages_show_list`. |
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_RPM`, `LABELER` | Gemini labeling. `LABELER=auto` uses Gemini when a key is set, else the rules; `rules` or `gemini` force one. |
| `YOUTUBE_DISCOVERY_QUOTA`, `MAX_COMPETITORS`, `LOOKBACK_DAYS`, `MAX_POSTS_PER_ACCOUNT`, `HASHTAG_MAX_PAGES` | Pipeline limits. |

## How it works

```
discover -> collect -> label -> rank -> the UI reads the database
```

1. **discover** searches YouTube for each search term, classifies the channels (agent, agency,
   carrier), keeps only the US-based ones, and picks the top competitors.
2. **collect** reads the last 90 days of posts: YouTube videos of the competitors, the Instagram
   accounts we could link to them, and the top posts of each Instagram hashtag.
3. **label** gives each post a topic, hook, call to action and a relevance flag (Gemini, or the
   rules when there is no key or Gemini fails).
4. **rank** scores every eligible post from 0 to 100 for the 7, 30 and 90 day windows, and scores
   each competitor from its posts.

How the score works: it blends the percentile of the post's engagement (adjusted for its age),
how far it beat that creator's usual, and its views. It is not a ratio to followers, because tiny
channels win any ratio. The formula, the thresholds and the reasons behind them are in `CLAUDE.md`
and `NOTES.md`. Settings live in `backend/app/ranking/config.py`.

## Commands

| Make target | What it does |
|---|---|
| `make setup` | Install, create `.env` and the database, seed the search terms |
| `make refresh` | Collect, label and rank (`DISCOVER=1` finds competitors first) |
| `make run` | Build the frontend and serve app and API on port 8000 |
| `make dev-api` / `make dev-web` | Development: backend with reload on :8000, Vite on :5173 (proxies `/api`) |
| `make discover` | Only the discovery step (about 3,000 quota units) |
| `make reset` | Delete all stored data and seed again |
| `make test` | Backend tests and lint, then frontend lint and build |

The same steps are available one by one, from `backend/`:

```bash
uv run python -m app.cli init-db | reset-db --yes | seed
uv run python -m app.cli discover
uv run python -m app.cli collect [--platform youtube|instagram]
uv run python -m app.cli label [--force] [--limit 100]
uv run python -m app.cli rank
uv run python -m app.cli refresh [--discover]
```

There are no migrations. After changing `app/models.py`, run `make reset` and refresh again.

## Gemini (optional)

With `GEMINI_API_KEY` set (and `LABELER` not `rules`), `label` uses Gemini for topic, hook, call to
action and relevance, and `discover` and `collect` ask it about accounts the rules cannot settle.
Without a key everything runs on the rules. The free tier allows about 10 requests a minute, so
labeling all posts takes around 20 minutes; `label --limit 100` does the 100 most engaging posts
first. Only public post text is sent.

## API

Interactive docs at http://localhost:8000/docs. All data endpoints take `window=7|30|90`
(default 7); anything else is a 422.

| Endpoint | What it gives |
|---|---|
| `GET /api/meta` | windows, platforms, taxonomy, thresholds, counts, last update |
| `GET /api/posts` | ranked posts: `platform`, `topic`, `hook_type`, `format`, `competitor_id`, `limit`, `offset` |
| `GET /api/competitors` | leaderboard; `include_low_sample` shows competitors with few posts |
| `GET /api/competitors/{id}` | one competitor: accounts, scores per window, top posts |
| `GET /api/insights` | average score per `group_by=hook_type`, `topic` or `format`, optional `platform` |
| `GET /api/runs`, `GET /api/keywords` | pipeline history and search terms |
| `POST /api/keywords`, `PATCH`/`DELETE /api/keywords/{id}` | add a search term (`platform` empty) or hashtag (`instagram`), turn it on or off, delete it |
| `GET /api/hashtag-budget` | Instagram's 30 different hashtags per 7 days: used, free, when each slot frees |
| `GET /api/health` | `{"status": "ok"}` |

Keywords are the only thing the API can change. There is no login, so keep the server local;
other websites cannot change them from a browser (CORS allows only the dev origin).

`format` takes `long_video`, `short_video` or `image` (Reels count as short videos, carousels as
images).

## Frontend

The UI has four tabs: **Top content** (ranked posts with filters), **Competitors** (leaderboard and
a page per competitor), **Insights** (average score per hook, topic or format) and **Sources**
(platforms, search terms and hashtags you can add, turn on or off and delete, the hashtag budget,
and the recent runs behind a dropdown). Everything you pick (tab,
window, platform, filters) is in the URL, so a view can be shared.

For development, run the backend (`make dev-api`) and the frontend (`make dev-web`) in two
terminals. Frontend commands, from `frontend/`: `pnpm dev`, `pnpm lint`, `pnpm build`.

## Limits worth knowing

- **Instagram has no author search.** Posts from hashtags have no author, no views and no
  followers, so they are judged by caption only ("likely" or "probable" US, never proven) and
  never appear in the competitor leaderboard. Accounts are linked to competitors only with strict
  evidence from YouTube channel text.
- **Instagram request limit.** The Graph API stops the whole app for about an hour when it is hit
  (error code 4). The collector stops cleanly and says so in the run log; run it again later.
- **Instagram image links expire** after about 4 days. Every collect renews them; an expired image
  shows a text placeholder.
- **YouTube** exposes no share counts, and Shorts are detected by duration (3 minutes or less).
- **US-based is a judgment** from the channel country, phone numbers, license mentions and, for
  the unclear cases, Gemini quoting the text it relied on. Hover a badge to see its evidence.
- **Instagram allows 30 different hashtags per 7 days.** Each hashtag run records the hashtags it
  searched (`runs.hashtags`); the Sources tab counts the slots from that. A database made before
  this column existed needs `ALTER TABLE runs ADD COLUMN hashtags VARCHAR;`.

## Tests

```bash
make test
```

Backend tests never call live APIs: collectors take an injected HTTP client and use recorded,
sanitized fixtures.
