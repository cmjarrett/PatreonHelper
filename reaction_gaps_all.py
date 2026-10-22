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


def slug(name):
    return re.sub(r"[^a-z0-9]+", "", name.lower()) or "creator"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--creators", required=True, help="the creators JSON")
    ap.add_argument("--root", required=True, help="library root")
    ap.add_argument("--aliases", help="reaction-aliases.json")
    ap.add_argument("--creator", help="only this creator (key in the JSON)")
    ap.add_argument("--out-dir", default=".", help="where the <slug>.tsv / -missing.txt / -collections.json go (default: here)")
    a = ap.parse_args()

    cfg = json.loads(Path(a.creators).read_text(encoding="utf-8"))
    defaults = cfg.get("_defaults") or {}
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [(name, c) for name, c in cfg.items() if not name.startswith("_") and isinstance(c, dict)
            and c.get("handling") in ("patreon", "collections") and c.get("url") and (not a.creator or name == a.creator)]
    if not todo:
        sys.exit("no creator with handling patreon/collections and a url" + (f" named {a.creator!r}" if a.creator else ""))
    commands = []
    for name, c in todo:
        s = slug(name)
        opts = {**defaults, **c}
        cmd = [sys.executable, str(HERE / "reaction_gaps.py"), "--root", a.root, "--creator", name, "--patreon", c["url"],
               "--save-tsv", str(out_dir / f"{s}.tsv"), "--out", str(out_dir / s)]
        if a.aliases:
            cmd += ["--aliases", a.aliases]
        if opts.get("new_shows", True):
            cmd.append("--include-new")
        if opts.get("movies"):
            cmd.append("--include-movies")
        if opts.get("include"):
            cmd += ["--only-collections", ",".join(opts["include"])]
        if opts.get("full_markers"):                     # creator's own words: ["watch along"]
            cmd += ["--full-marker", "|".join(opts["full_markers"])]
        if opts.get("cut_markers"):                      # ["early access", "first time"]
            cmd += ["--cut-marker", "|".join(opts["cut_markers"])]
        if opts.get("unmarked"):                         # "full" | "edited"
            cmd += ["--unmarked", opts["unmarked"]]
        print(f"\n{'=' * 78}\n{name}  ({c['url']})\n{'=' * 78}", flush=True)
        r = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace")
        coll_file = out_dir / f"{s}-collections.json"
        if coll_file.exists():
            counts = Counter(json.loads(coll_file.read_text(encoding="utf-8")).values())
            print("collections on Patreon (for an `include` list): " + "; ".join(f"{t} ({n})" for t, n in counts.most_common()))
        if r.returncode == 0:
            commands.append(f'.\\Download-Creator.ps1 -Creator "{name}" -ListFile {out_dir / (s + "-missing.txt")}')
        else:
            print(f"!! reaction_gaps failed for {name} (exit {r.returncode})")
    print("\nWhen ready, per creator:\n  " + "\n  ".join(commands))


if __name__ == "__main__":
    main()
