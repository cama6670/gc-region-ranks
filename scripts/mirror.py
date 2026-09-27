#!/usr/bin/env python3
"""Mirror Silph Scope competition ladders and add region / country ranks.

Silph Scope crawls the in-game Pokemon Champions leaderboard (top 1000) a few
times an hour and serves each crawl as a "snapshot" from its JSON API. This
script copies the latest snapshot of each configured division into
<out>/data/<comid>.json with two extra ranks per trainer:

  region_rank   position among trainers of the same region (in the top 1000)
  country_rank  position among trainers of the same country (in the top 1000)

One-shot:  python scripts/mirror.py                 (writes site/data/, then serve site/)
Watch:     python scripts/mirror.py --out public --watch --git-push   (what the workflow runs)
List ids:  python scripts/mirror.py --list
"""
import argparse
import gzip
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

API = "https://silph-scope.com/api"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Poll the tiny /leaderboard response (~200 bytes; it carries the latest snapshot id) and only
# download the ~50 KB gzipped ladder when that id changes.
POLL_SECONDS = 60
# Silph Scope usually captures final standings ~75 minutes after a competition closes.
GRACE_AFTER_END = 3 * 3600
LEAD_BEFORE_START = 3600

# The game's country code is <region digit><2-digit country>; mirrors Silph Scope's own tables.
REGIONS = {
    1: "Africa", 2: "North America", 3: "Latin America", 4: "Oceania",
    5: "Asia", 6: "Europe", 7: "Middle East",
}
COUNTRIES = {
    101: "South Africa",
    201: "Canada", 202: "USA", 203: "USA", 204: "USA", 205: "USA",
    301: "Chile", 302: "Mexico", 303: "Brazil", 304: "Argentina", 305: "Bolivia",
    306: "Colombia", 307: "Paraguay", 308: "Peru", 309: "Ecuador",
    401: "Australia", 402: "New Zealand",
    501: "China", 502: "Hong Kong", 503: "Japan", 504: "South Korea", 505: "Malaysia",
    506: "Philippines", 507: "Singapore", 508: "Taiwan", 509: "Thailand", 510: "Indonesia",
    601: "Austria", 602: "Belgium", 603: "France", 604: "Germany", 605: "Ireland",
    606: "Italy", 607: "Netherlands", 608: "Portugal", 609: "Spain", 610: "Switzerland",
    611: "UK", 612: "Denmark", 613: "Finland", 614: "Norway", 615: "Sweden", 616: "Poland",
    701: "Israel", 702: "UAE", 703: "Saudi Arabia", 704: "Egypt",
}
FLAGS = {
    "South Africa": "ZA", "Canada": "CA", "USA": "US", "Chile": "CL", "Mexico": "MX",
    "Brazil": "BR", "Argentina": "AR", "Bolivia": "BO", "Colombia": "CO", "Paraguay": "PY",
    "Peru": "PE", "Ecuador": "EC", "Australia": "AU", "New Zealand": "NZ", "China": "CN",
    "Hong Kong": "HK", "Japan": "JP", "South Korea": "KR", "Malaysia": "MY",
    "Philippines": "PH", "Singapore": "SG", "Taiwan": "TW", "Thailand": "TH",
    "Indonesia": "ID", "Austria": "AT", "Belgium": "BE", "France": "FR", "Germany": "DE",
    "Ireland": "IE", "Italy": "IT", "Netherlands": "NL", "Portugal": "PT", "Spain": "ES",
    "Switzerland": "CH", "UK": "GB", "Denmark": "DK", "Finland": "FI", "Norway": "NO",
    "Sweden": "SE", "Poland": "PL", "Israel": "IL", "UAE": "AE", "Saudi Arabia": "SA",
    "Egypt": "EG",
}


def user_agent():
    repo = os.environ.get("GITHUB_REPOSITORY")
    where = f"https://github.com/{repo}" if repo else "local run"
    return f"gc-region-ranks/1.0 (+{where})"


def get_json(path, retries=3):
    req = urllib.request.Request(
        API + path, headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return json.loads(body)
        except Exception as e:  # network blips, 5xx, bad JSON
            if attempt == retries - 1:
                raise
            print(f"  retry {path}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))


def flag(name):
    code = FLAGS.get(name)
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code) if code else ""


def group_ranks(rows, key):
    """Competition ranking ("1224") by global rank within each group given by key(row)."""
    seen, last = {}, {}
    out = []
    for r in rows:  # rows are in global-rank order
        k = key(r)
        n = seen.get(k, 0) + 1
        seen[k] = n
        prev = last.get(k)
        rank = prev[1] if prev and prev[0] == r["rank"] else n
        last[k] = (r["rank"], rank)
        out.append(rank)
    return out


def enrich(ladder):
    rows = sorted(ladder, key=lambda r: (r["rank"], -r["rating"]))
    out = []
    for r in rows:
        code = int(r.get("country") or 0)
        region = code // 100 if code // 100 in REGIONS else 0
        country = COUNTRIES.get(code)
        if not country:
            country = f"Other ({REGIONS[region]})" if region else "Unknown"
        games = r["wins"] + r["losses"] + (r.get("draws") or 0)
        out.append({
            "rank": r["rank"],
            "name": r["name"],
            "country": country,
            "flag": flag(country),
            "region": REGIONS.get(region, "Unknown"),
            "rating": round(r["rating"], 3),
            "wins": r["wins"],
            "losses": r["losses"],
            "draws": r.get("draws") or 0,
            "win_pct": round(r["wins"] / games * 100, 1) if games else 0.0,
            "id": r["id"],
        })
    for row, rr, cr in zip(out,
                           group_ranks(out, lambda r: r["region"]),
                           group_ranks(out, lambda r: r["country"])):
        row["region_rank"] = rr
        row["country_rank"] = cr
    return out


def load_divisions(meta):
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    comps = {c["comid"]: c for c in meta["competitions"]}
    divs = []
    for d in cfg["divisions"]:
        c = comps.get(d["id"])
        if not c:
            print(f"warning: {d['id']} ({d.get('label')}) is not a Silph Scope competition", file=sys.stderr)
            continue
        divs.append({"id": d["id"], "label": d["label"], "title": c["title"],
                     "subtitle": c.get("subtitle", ""), "start": c["start"], "end": c["end"]})
    return divs


def is_active(div, now):
    return div["start"] - LEAD_BEFORE_START <= now <= div["end"] + GRACE_AFTER_END


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def existing_snapshot(out, comid):
    try:
        with open(os.path.join(out, "data", comid + ".json"), encoding="utf-8") as f:
            return json.load(f)["snapshot"]["id"]
    except (OSError, ValueError, KeyError):
        return None


def mirror_division(out, div):
    data = get_json(f"/ladder?format={div['id']}")
    snap = data["snapshot"]
    rows = enrich(data.get("ladder") or [])
    write_json(os.path.join(out, "data", div["id"] + ".json"), {
        "division": div,
        "snapshot": {"id": snap["id"], "leaderboard_time": snap["tsp"], "silph_fetched_at": snap.get("fetched_at")},
        "mirrored_at": int(time.time()),
        "players": rows,
    })
    return snap["id"], len(rows)


def write_index(out, divs):
    entries = []
    for d in divs:
        try:
            with open(os.path.join(out, "data", d["id"] + ".json"), encoding="utf-8") as f:
                snap = json.load(f)["snapshot"]
        except (OSError, ValueError):
            continue
        entries.append({**d, "snapshot": snap})
    write_json(os.path.join(out, "data", "index.json"), {"updated": int(time.time()), "divisions": entries})


def git_publish(out, message):
    """Make <out> the single commit on gh-pages and force-push it (keeps data history out of the repo)."""
    def git(*args, check=True):
        return subprocess.run(["git", "-C", out, *args], check=check, capture_output=True, text=True)
    git("add", "-A")
    committed = bool(git("status", "--porcelain").stdout.strip())
    if committed:
        has_head = git("rev-parse", "--verify", "HEAD", check=False).returncode == 0
        git("commit", "-q", *(["--amend"] if has_head else []), "-m", message)
    git("push", "-q", "-f", "origin", "HEAD:gh-pages")
    if committed:
        print(f"  published: {message}")


def ts(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def run(args):
    os.makedirs(os.path.join(args.out, "data"), exist_ok=True)
    meta = get_json("/meta")
    divs = load_divisions(meta)
    if not divs:
        sys.exit("no configured divisions found")
    now = time.time()
    if args.only_if_active and not any(is_active(d, now) for d in divs):
        print("no configured division is live; leaving the published data alone")
        return

    deadline = now + args.max_minutes * 60
    last = {d["id"]: existing_snapshot(args.out, d["id"]) for d in divs}
    index_path = os.path.join(args.out, "data", "index.json")
    needs_push = args.git_push  # first pass also deploys page changes that came with a push to main
    while True:
        changed = []
        for d in divs:
            try:
                # cheap probe: /leaderboard is empty for competitions but reports the newest snapshot
                if last[d["id"]] is not None:
                    probe = get_json(f"/leaderboard?format={d['id']}")["snapshot"]["id"]
                    if probe == last[d["id"]]:
                        continue
                sid, n = mirror_division(args.out, d)
                last[d["id"]] = sid
                changed.append(f"{d['label']} #{sid}")
                print(f"{d['label']}: snapshot {sid}, {n} players")
            except Exception as e:
                print(f"{d['label']}: fetch failed: {e}", file=sys.stderr)
        if changed or not os.path.exists(index_path):
            write_index(args.out, divs)
        if args.git_push and (changed or needs_push):
            what = "data: " + ", ".join(changed) if changed else "site update"
            try:
                git_publish(args.out, f"{what} @ {ts(time.time())}")
                needs_push = False
            except subprocess.CalledProcessError as e:
                needs_push = True  # retry on the next pass
                print(f"push failed: {e.stderr}", file=sys.stderr)

        if not args.watch:
            return
        now = time.time()
        if not any(is_active(d, now) for d in divs):
            print("all configured divisions are over; stopping")
            return
        if now + POLL_SECONDS > deadline:
            print("time budget used up; the next scheduled run takes over")
            return
        time.sleep(POLL_SECONDS)


def list_competitions():
    meta = get_json("/meta")
    for c in sorted(meta["competitions"], key=lambda c: -c["start"]):
        sub = f" - {c['subtitle']}" if c.get("subtitle") else ""
        print(f"{c['comid']}  {ts(c['start'])[:10]} -> {ts(c['end'])[:10]}  {c['title']}{sub}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=os.path.join(ROOT, "site"), help="site directory to write data/ into")
    p.add_argument("--watch", action="store_true", help="keep polling while a division is live")
    p.add_argument("--max-minutes", type=float, default=340, help="stop watching after this long")
    p.add_argument("--only-if-active", action="store_true", help="do nothing unless a division is live")
    p.add_argument("--git-push", action="store_true", help="commit and force-push <out> to gh-pages on change")
    p.add_argument("--list", action="store_true", help="list Silph Scope competition ids and exit")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.list:
        list_competitions()
    else:
        run(args)


if __name__ == "__main__":
    main()
