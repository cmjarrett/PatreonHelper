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
    # ---- 1. arguments ----
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--creators", required=True, help="the creators JSON")
    parser.add_argument("--root", required=True, help="library root")
    parser.add_argument("--aliases", help="reaction-aliases.json")
    parser.add_argument("--creator", help="only this creator (key in the JSON)")
    parser.add_argument("--out-dir", default=".", help="where the <slug>.tsv / -missing.txt / -collections.json go (default: here)")
    args = parser.parse_args()

    # ---- 2. which creators to run ----
    config = json.loads(Path(args.creators).read_text(encoding="utf-8"))
    defaults = config.get("_defaults") or {}
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    todo = []
    for name, creator_config in config.items():
        if name.startswith("_") or not isinstance(creator_config, dict):    # "_defaults" and comments
            continue
        if creator_config.get("handling") not in HANDLINGS_LISTED_HERE or not creator_config.get("url"):
            continue
        if args.creator and name != args.creator:
            continue
        todo.append((name, creator_config))

    if not todo:
        sys.exit("no creator with handling patreon/collections and a url" + (f" named {args.creator!r}" if args.creator else ""))

    # ---- 3. one reaction_gaps.py run per creator ----
    download_commands = []
    for name, creator_config in todo:
        creator_slug = slug(name)
        options = {**defaults, **creator_config}               # the creator's own settings win over _defaults

        cmd = [sys.executable, str(HERE / "reaction_gaps.py"), "--root", args.root, "--creator", name,
               "--patreon", creator_config["url"],
               "--save-tsv", str(out_dir / f"{creator_slug}.tsv"), "--out", str(out_dir / creator_slug)]
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

        if result.returncode == 0:
            missing_list = out_dir / (creator_slug + "-missing.txt")
            download_commands.append(f'.\\Download-Creator.ps1 -Creator "{name}" -ListFile {missing_list}')
        else:
            print(f"!! reaction_gaps failed for {name} (exit {result.returncode})")

    # ---- 4. the download command per creator, to run when ready ----
    print("\nWhen ready, per creator:\n  " + "\n  ".join(download_commands))


if __name__ == "__main__":
    main()
