#!/usr/bin/env python3
"""Read-only survey of one creator's folder in the reaction library: what is there, and what looks wrong.

  python reaction_survey.py --root "\\\\nas\\media\\reaction" --creator "Some Creator"
  python reaction_survey.py --root "\\\\nas\\media\\reaction" --creator "Some Creator" --out survey.tsv

It only lists folders and reads file sizes. It never renames, moves or deletes; the report is for you to act on.
Sections:
  folders        every creator folder whose name matches (so "SomeCreator" next to "Some Creator" shows up)
  per show       files, size, how many follow the library naming ("Show - S01E08.ext")
  unfinished     .part / .ytdl files, and video files under --min-mb (a cut-off download)
  duplicates     the same season and episode twice in one show (ranges count for each episode they cover)
  naming         video files that do not follow the library naming (reaction_rename.py --tidy handles most)
  loose files    video files directly in the creator folder, outside any show
  not video      other files (subtitles, images, text, audio)
  empty          folders with nothing in them
--out writes every file as a TSV line: section, size in bytes, path.
"""
import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import reaction_rename as rr  # noqa: E402

UNFINISHED = {".part", ".ytdl", ".tmp"}
EPISODE = re.compile(r" - S(\d{2})E(\d{2})(?:-E?(\d{2}))?")


def size_text(size):
    return f"{size / 2**30:.1f} GB" if size >= 2**30 else f"{size / 2**20:.0f} MB"


def survey(root, creator, min_mb=20, other_names=()):
    """(folders, shows, findings): findings = {section: [(size, path)]}, shows = {show: [files, bytes, conventional]}."""
    folders = rr.creator_folders(root, [creator, *other_names])
    shows = defaultdict(lambda: [0, 0, 0])
    findings = defaultdict(list)
    episodes = defaultdict(list)                           # (show key, season, episode) -> [(size, path)], across the folders

    for folder in folders:
        for dirpath, dirnames, filenames in os.walk(folder):
            here = Path(dirpath)
            if not dirnames and not filenames:
                findings["empty"].append((0, here))
            relative = here.relative_to(folder)
            show = relative.parts[0] if relative.parts else "(creator folder)"
            for name in filenames:
                file = here / name
                try:
                    size = file.stat().st_size
                except OSError:
                    size = 0
                suffix = file.suffix.lower()
                is_video = suffix in rr.VIDEO
                shows[show][0] += 1
                shows[show][1] += size

                if suffix in UNFINISHED:
                    findings["unfinished"].append((size, file))
                    continue
                if not is_video:
                    findings["not video"].append((size, file))
                    continue
                if size < min_mb * 2**20:
                    findings["unfinished"].append((size, file))
                if not relative.parts:
                    findings["loose files"].append((size, file))
                    continue

                match = EPISODE.search(file.stem)
                in_movies = "movies" in (part.lower() for part in relative.parts)
                if match:
                    shows[show][2] += 1
                    last = int(match[3] or match[2])
                    for episode in range(int(match[2]), last + 1):
                        episodes[(rr.key(show), int(match[1]), episode)].append((size, file))
                elif not in_movies:                        # movie folders keep their titles
                    findings["naming"].append((size, file))

    for (_show, _season, _episode), files in sorted(episodes.items()):
        if len({path for _, path in files}) > 1:
            for entry in files:
                if entry not in findings["duplicates"]:
                    findings["duplicates"].append(entry)
    return folders, shows, findings


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="library root (only read)")
    parser.add_argument("--creator", required=True, help="the creator folder; spelling, spaces and case don't matter")
    parser.add_argument("--creator-folder", action="append", default=[], metavar="NAME",
                        help="another spelling of the folder that differs by a letter (repeatable)")
    parser.add_argument("--min-mb", type=int, default=20, help="a video file smaller than this counts as unfinished (default 20)")
    parser.add_argument("--out", help="write every finding as TSV: section, bytes, path")
    parser.add_argument("--limit", type=int, default=40, help="lines printed per section (default 40; the TSV has all)")
    args = parser.parse_args()

    folders, shows, findings = survey(args.root, args.creator, args.min_mb, args.creator_folder)
    if not folders:
        existing = ", ".join(sorted(p.name for p in Path(args.root).iterdir() if p.is_dir()))
        sys.exit(f"no folder matching {args.creator!r} under {args.root}. Folders there: {existing}")

    print("folders:")
    for folder in folders:
        print(f"   {folder}")
    if len(folders) > 1:
        print("   !! more than one folder for this creator: they should be merged into one")

    total_files = sum(v[0] for v in shows.values())
    total_size = sum(v[1] for v in shows.values())
    print(f"\nper show ({total_files} files, {size_text(total_size)}):")
    for show in sorted(shows, key=str.lower):
        files, size, conventional = shows[show]
        print(f"   {show}: {files} files, {size_text(size)}, {conventional} in library naming")

    for section in ("unfinished", "duplicates", "naming", "loose files", "not video", "empty"):
        entries = sorted(findings.get(section, []), key=lambda entry: str(entry[1]).lower())
        print(f"\n{section}: {len(entries)}" + (f" ({size_text(sum(size for size, _ in entries))})" if entries else ""))
        for size, path in entries[:args.limit]:
            print(f"   {size_text(size):>8}  {path}")
        if len(entries) > args.limit:
            print(f"   ... {len(entries) - args.limit} more (see --out)")

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            for section, entries in findings.items():
                for size, path in sorted(entries, key=lambda entry: str(entry[1]).lower()):
                    fh.write(f"{section}\t{size}\t{path}\n")
        print(f"\nevery finding -> {args.out}")


if __name__ == "__main__":
    main()
