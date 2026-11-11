#!/usr/bin/env python3
"""Gap lists for every creator in a creators JSON, from Patreon's public API (collections included), nothing downloaded.

  python reaction_gaps_all.py --creators C:\\path\\reaction-creators.json --root "\\\\nas\\media\\reaction" --aliases C:\\path\\reaction-aliases.json
  python reaction_gaps_all.py ... --creator "DN Reacts"          # one creator

Per creator with handling "patreon" or "collections" and a url, this runs
  reaction_gaps.py --patreon <url> --save-tsv <slug>.tsv --out <slug> [--include-new] [--include-movies] [--only-collections ...]
and prints its per-show summary; the download list is <slug>-missing.txt, the collection names (with post counts) are
printed so an `include` list can be filled in. Then, per creator, when you decide to:
  .\\Download-Creator.ps1 -Creator "<name>" -ListFile <slug>-missing.txt

Creators JSON (the owner's private file): {"_defaults": {"new_shows": true, "movies": false, "include": []},
 "<library folder>": {"url": "https://www.patreon.com/<name>", "handling": "patreon"|"collections"|..., "include": ["Show", ...]}}
`include` (creator or defaults) = only these Patreon collections; empty = everything.
`exclude` (creator and defaults together) = shows or collections never to download; "sync": false = leave the
creator out of every run (not subscribed at the moment).

For a scheduled run (Sync-Reactions.ps1 calls it this way):
  --archive <file>      the download record: posts in it are never listed again, and the posts the library holds are
                        added to it, so deleting a file later does not bring the post back
  --never-file <file>   the never-keep list (reaction_ledger.py never ...)
  --offline             use the saved <slug>.tsv listings, no Patreon request
The plan is written to <out-dir>/sync-plan.json: per creator the download list and how many posts it holds.
"""
import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

# only creators handled through Patreon's public API are listed here
HANDLINGS_LISTED_HERE = ("patreon", "collections")


def slug(name):
    """A file-name prefix for a creator: lower-case letters and digits only ("DN Reacts" -> "dnreacts")."""
    return re.sub(r"[^a-z0-9]+", "", name.lower()) or "creator"


def main():
    for stream in (sys.stdout, sys.stderr):                # a title the console code page can't hold must not stop the run
        stream.reconfigure(errors="replace")

    # ---- 1. arguments ----
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--creators", required=True, help="the creators JSON")
    parser.add_argument("--root", required=True, help="library root")
    parser.add_argument("--aliases", help="reaction-aliases.json")
    parser.add_argument("--creator", help="only this creator (key in the JSON)")
    parser.add_argument("--out-dir", default=".", help="where the <slug>.tsv / -missing.txt / -collections.json go (default: here)")
    parser.add_argument("--archive", help="the download record (yt-dlp archive): read to leave out what was fetched "
                        "before, and the posts the library already holds are added to it")
    parser.add_argument("--never-file", help="the never-keep list ('Creator | Show' per line)")
    parser.add_argument("--offline", action="store_true", help="use the saved listings in --out-dir, no Patreon request")
    args = parser.parse_args()

    # ---- 2. which creators to run ----
    config = json.loads(Path(args.creators).read_text(encoding="utf-8"))
    defaults = config.get("_defaults") or {}
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # An unreachable or empty library would make every post look missing: stop instead of listing everything.
    root = Path(args.root)
    if not root.is_dir() or not any(entry.is_dir() for entry in root.iterdir()):
        sys.exit(f"library root {args.root} is not reachable or has no creator folders: nothing listed")

    todo = []
    for name, creator_config in config.items():
        if name.startswith("_") or not isinstance(creator_config, dict):    # "_defaults" and comments
            continue
        if creator_config.get("handling") not in HANDLINGS_LISTED_HERE or not creator_config.get("url"):
            continue
        if args.creator and name != args.creator:
            continue
        if creator_config.get("sync") is False:                # not subscribed at the moment
            print(f"-- {name}: left out (\"sync\": false)")
            continue
        todo.append((name, creator_config))

    if not todo:
        sys.exit("no creator with handling patreon/collections and a url" + (f" named {args.creator!r}" if args.creator else ""))

    # ---- 3. one reaction_gaps.py run per creator ----
    download_commands = []
    plan = []                                                  # for Sync-Reactions.ps1: what to download per creator
    for name, creator_config in todo:
        creator_slug = slug(name)
        options = {**defaults, **creator_config}               # the creator's own settings win over _defaults

        listing = out_dir / f"{creator_slug}.tsv"
        cmd = [sys.executable, str(HERE / "reaction_gaps.py"), "--root", args.root, "--creator", name,
               "--out", str(out_dir / creator_slug)]
        if args.offline:
            if not listing.exists():
                print(f"-- {name}: left out (--offline and no saved listing {listing})")
                continue
            cmd += ["--from-tsv", str(listing)]
        else:
            cmd += ["--patreon", creator_config["url"], "--save-tsv", str(listing)]
        if args.archive:
            cmd += ["--archive", args.archive, "--seed-archive", args.archive]
        if args.never_file:
            cmd += ["--never-file", args.never_file]
        # never these shows: the creator's own list and the defaults' together
        for show in list(defaults.get("exclude") or []) + list(creator_config.get("exclude") or []):
            cmd += ["--never", show]
        # "folders": other spellings of this creator's library folder (a name that differs by a letter)
        for folder in creator_config.get("folders") or []:
            cmd += ["--creator-folder", folder]
        if args.aliases:
            cmd += ["--aliases", args.aliases]
        if options.get("new_shows", True):
            cmd.append("--include-new")
        if options.get("movies"):
            cmd.append("--include-movies")
        if options.get("include"):
            cmd += ["--only-collections", ",".join(options["include"])]
        if options.get("full_markers"):                     # creator's own words: ["watch along"]
            cmd += ["--full-marker", "|".join(options["full_markers"])]
        if options.get("cut_markers"):                      # ["early access", "first time"]
            cmd += ["--cut-marker", "|".join(options["cut_markers"])]
        if options.get("unmarked"):                         # "full" | "edited"
            cmd += ["--unmarked", options["unmarked"]]

        banner = "=" * 78
        print(f"\n{banner}\n{name}  ({creator_config['url']})\n{banner}", flush=True)
        result = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace")

        # the collection names with post counts, so an `include` list can be filled in
        collections_file = out_dir / f"{creator_slug}-collections.json"
        if collections_file.exists():
            post_counts = Counter(json.loads(collections_file.read_text(encoding="utf-8")).values())
            listing = "; ".join(f"{title} ({count})" for title, count in post_counts.most_common())
            print("collections on Patreon (for an `include` list): " + listing)

        missing_list = out_dir / (creator_slug + "-missing.txt")
        if result.returncode == 0:
            urls = [line for line in missing_list.read_text(encoding="utf-8").splitlines() if line.strip()]
            plan.append({"creator": name, "list": str(missing_list), "count": len(urls)})
            download_commands.append(f'.\\Download-Creator.ps1 -Creator "{name}" -ListFile {missing_list}')
        else:
            print(f"!! reaction_gaps failed for {name} (exit {result.returncode})")

    # ---- 4. the download command per creator, to run when ready ----
    (out_dir / "sync-plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\nWhen ready, per creator:\n  " + "\n  ".join(download_commands))


if __name__ == "__main__":
    main()
