# GC Regional Ranks

Pokémon Champions Global Challenge ladders (top 1000) with a **region rank** and **country rank**
for every trainer, next to the global rank. Data comes from [Silph Scope](https://silph-scope.com/).

## How the data flows

```
in-game leaderboard ──(Silph Scope crawl, ~3x/hour)──> silph-scope.com/api/ladder?format=<competition id>
      │  refreshes every ~15 min                                   │
      │                                                            ▼
      │                                  scripts/mirror.py (GitHub Actions, checks every 60 s)
      │                                    adds region_rank / country_rank
      │                                                            │  force-push data/*.json
      │                                                            ▼
      └──────────────────────────────────────────────> gh-pages branch ──> GitHub Pages (site/index.html,
                                                                             reloads data every 60 s)
```

- The game refreshes its leaderboard about every 15 minutes. Silph Scope crawls it at roughly :00, :22
  and :44 past the hour, so its snapshots lag the game by 7–22 minutes.
- Every 60 s the mirror sends Silph Scope a ~200-byte request (`/api/leaderboard?format=<id>`) that
  returns the newest snapshot id. It downloads the full ladder (~50 KB gzipped) only when that id changes.
  New Silph Scope data reaches this site about 1–2 minutes after Silph Scope gets it.
- A trainer's region is the hundreds digit of the game's country code
  (1 Africa, 2 North America, 3 Latin America, 4 Oceania, 5 Asia, 6 Europe, 7 Middle East).
  This is the same grouping Silph Scope uses in its region filter.

**Limitation:** the in-game leaderboard only exposes the global top 1000. A region rank here means
"position among trainers from that region who are in the global top 1000". Players outside the top 1000
are not visible anywhere.

## Setup (one time)

1. Push this folder to a **public** GitHub repo on `main`. The poller runs for hours while an event is
   live, and Actions minutes are free only on public repos.
2. The push starts the `Mirror ladders` workflow, which creates the `gh-pages` branch.
   You can also start it from **Actions → Mirror ladders → Run workflow**.
3. **Settings → Pages → Build and deployment → Deploy from a branch → `gh-pages` / `(root)`.**
4. The site is at `https://<user>.github.io/<repo>/`. Share a filtered view with
   `?div=juniors&region=north-america` or `?div=masters&country=usa`.

## Tracking a new competition

```sh
python scripts/mirror.py --list        # every competition id Silph Scope knows about
```

Put the ids you want in `config.json` and push. The workflow restarts right away with the new config:

```json
{ "divisions": [ { "id": "ic178714271270xvovwl", "label": "Masters" },
                 { "id": "ic178714175325wbiwzh", "label": "Juniors" } ] }
```

The poller only runs from 1 h before a division starts until 3 h after it ends. Silph Scope usually
captures final standings about 75 minutes after the close. Outside that window, the hourly
scheduled run checks the dates and exits within seconds.

## Running locally

```sh
python scripts/mirror.py               # writes site/data/*.json (Python 3.9+, stdlib only)
python -m http.server -d site 8000     # open http://localhost:8000
python scripts/mirror.py --watch       # keep it updating
```

## Notes

- GitHub disables scheduled workflows in repos with no activity for 60 days. Push anything,
  or re-enable the workflow in the Actions tab, before the next event.
- `gh-pages` always holds a single commit that is replaced on every update, so the repo doesn't grow.
- Silph Scope's `robots.txt` disallows `/api/`. This mirror identifies itself with a User-Agent that
  links to the repo and polls only the tiny snapshot-id endpoint. Asking the maintainers first
  (inquiries@silph-scope.com) is the polite route, and they may even add region ranks to their own
  ladder view.
