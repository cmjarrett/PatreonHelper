#!/usr/bin/env python3
"""The download record: what was fetched once, and what you never want.

Two small files decide what a later run may download, and neither looks at what is on disk today:
  * the download record   yt-dlp's archive file ("patreon <post id>" per line, default C:\\patreon\\downloaded.txt).
                          yt-dlp adds a line for every post it downloads and refuses to fetch a post that is in it.
                          The gap finder reads it too (--archive), so a post you downloaded, copied to the library
                          and deleted again is "fetched before", not "missing".
  * the never-keep list   a text file, one "Creator | Show" per line (default C:\\patreon\\never-keep.txt).
                          "Creator | *" is the whole creator, "* | Show" is that show from every creator.

Commands:
  python reaction_ledger.py status
  python reaction_ledger.py seed --inbox C:\\patreon\\inbox             # ids in the file names: "Title [123456].mp4"
  python reaction_ledger.py seed --ids-from C:\\patreon\\gaps\\somecreator-missing.txt
        every post in that file counts as fetched: use it for a creator you have been through already
        ("only new posts from now on"), or for an old URL list you know you downloaded
  python reaction_ledger.py never "Some Creator" "Some Show"         # add; --remove takes it out again
  python reaction_ledger.py never "Some Creator"                     # the whole creator
Nothing here downloads, moves or deletes a video.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import reaction_rename as rr  # noqa: E402

DEFAULT_ARCHIVE = r"C:\patreon\downloaded.txt"
DEFAULT_NEVER = r"C:\patreon\never-keep.txt"

MEDIA = rr.VIDEO | {".m4a", ".mp3", ".opus"}
# a post id in a Patreon URL: /posts/123456 or /posts/some-title-123456
POST_URL_ID = re.compile(r"patreon\.com/posts/(?:[^\s/?#]*?-)?(\d+)(?=[\s/?#]|$)")
ARCHIVE_LINE = re.compile(r"^(patreon|youtube|vimeo)\s+(\S+)$", re.I)
BARE_ID = re.compile(r"^\d{5,}$")
FILE_ID = re.compile(r"\[([^\[\]]+)\]$")                # the "[id]" yt-dlp puts at the end of the file name


# ======================================================================================================
# The download record (yt-dlp archive)
# ======================================================================================================

def read_archive(path):
    """Every line of the record as a set ("patreon 123", "youtube abc"); a missing file is an empty record."""
    path = Path(path)
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()}


def fetched_post_ids(path):
    """The Patreon post ids in the record."""
    return {line.split()[1] for line in read_archive(path) if line.startswith("patreon ")}


def add_to_archive(path, lines):
    """Append the lines that are not in the record yet; returns how many were added. Never removes a line."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_archive(path)
    new_lines = sorted(set(lines) - existing)
    if new_lines:
        needs_newline = path.exists() and path.stat().st_size and not path.read_bytes().endswith(b"\n")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(("\n" if needs_newline else "") + "".join(line + "\n" for line in new_lines))
    return len(new_lines)


def ids_in_folder(folder):
    """Record lines for finished downloads under `folder`, from the "[id]" in their names. Unfinished files
    (.part, .ytdl) are left out: yt-dlp should fetch those again."""
    lines = set()
    for file in Path(folder).rglob("*"):
        if not file.is_file() or file.suffix.lower() not in MEDIA:
            continue
        match = FILE_ID.search(file.stem)
        if not match:
            continue
        file_id = match.group(1)
        if file_id.isdigit():                              # Patreon post ids are plain numbers
            lines.add(f"patreon {file_id}")
        elif re.fullmatch(r"[\w-]{11}", file_id):          # a post that embeds a YouTube video
            lines.add(f"youtube {file_id}")
    return lines


def ids_in_text(path):
    """Record lines for every post named in a text file: Patreon post URLs, record lines, or bare post ids."""
    lines = set()
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        text = raw.strip()
        archive_line = ARCHIVE_LINE.match(text)
        if archive_line:
            lines.add(f"{archive_line.group(1).lower()} {archive_line.group(2)}")
        elif BARE_ID.match(text):
            lines.add(f"patreon {text}")
        else:
            lines.update(f"patreon {post_id}" for post_id in POST_URL_ID.findall(text))
    return lines


# ======================================================================================================
# The never-keep list
# ======================================================================================================

def read_never(path):
    """[(creator, show)] as written in the file; '*' on either side means all. A missing file is an empty list."""
    path = Path(path)
    if not path.exists():
        return []
    entries = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        creator, _, show = text.partition("|")
        entries.append((creator.strip() or "*", show.strip() or "*"))
    return entries


def never_keys_for(path, creator):
    """The show keys this creator must never get, from the file; {'*'} when the whole creator is out."""
    keys = set()
    for entry_creator, show in read_never(path):
        if entry_creator == "*" or rr.key(entry_creator) == rr.key(creator):
            keys.add("*" if show == "*" else rr.key(show))
    return keys


def write_never(path, entries):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# Never download these. One per line: Creator | Show   (Creator | * = the whole creator, * | Show = from everyone)\n"
    body = "".join(f"{creator} | {show}\n" for creator, show in entries)
    path.write_text(header + body, encoding="utf-8")


# ======================================================================================================
# Command line
# ======================================================================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="add posts to the download record")
    seed.add_argument("--archive", default=DEFAULT_ARCHIVE)
    seed.add_argument("--inbox", action="append", default=[], metavar="FOLDER",
                      help="a folder of downloads named 'Title [id].ext' (repeatable)")
    seed.add_argument("--ids-from", action="append", default=[], metavar="FILE",
                      help="a text file of Patreon post URLs, record lines or post ids (repeatable)")
    seed.add_argument("--dry-run", action="store_true", help="count only, write nothing")

    never = sub.add_parser("never", help="add a show or a creator to the never-keep list")
    never.add_argument("creator", help="the creator's library folder, or * for every creator")
    never.add_argument("show", nargs="?", default="*", help="the show (library folder or Patreon collection); "
                       "left out = the whole creator")
    never.add_argument("--file", default=DEFAULT_NEVER)
    never.add_argument("--remove", action="store_true", help="take the entry out again")

    status = sub.add_parser("status", help="what the record and the never-keep list hold")
    status.add_argument("--archive", default=DEFAULT_ARCHIVE)
    status.add_argument("--file", default=DEFAULT_NEVER)

    args = parser.parse_args()

    if args.command == "seed":
        if not args.inbox and not args.ids_from:
            sys.exit("give --inbox <folder> and/or --ids-from <file>")
        lines = set()
        for folder in args.inbox:
            found = ids_in_folder(folder)
            print(f"{folder}: {len(found)} finished downloads with an id in the name")
            lines |= found
        for file in args.ids_from:
            found = ids_in_text(file)
            print(f"{file}: {len(found)} posts")
            lines |= found
        if args.dry_run:
            new = len(lines - read_archive(args.archive))
            print(f"dry run: {new} would be added to {args.archive} ({len(lines) - new} are in it already)")
        else:
            added = add_to_archive(args.archive, lines)
            print(f"added {added} to {args.archive} ({len(lines) - added} were in it already)")

    elif args.command == "never":
        entries = read_never(args.file)
        same = [e for e in entries if rr.key(e[0]) == rr.key(args.creator) and rr.key(e[1]) == rr.key(args.show)
                or e == (args.creator, args.show)]
        label = f"{args.creator} | {args.show}"
        if args.remove:
            if not same:
                sys.exit(f"not in {args.file}: {label}")
            write_never(args.file, [e for e in entries if e not in same])
            print(f"removed from {args.file}: {label}")
        elif same:
            print(f"already in {args.file}: {label}")
        else:
            write_never(args.file, entries + [(args.creator, args.show)])
            print(f"added to {args.file}: {label}")

    elif args.command == "status":
        record = read_archive(args.archive)
        by_site = {}
        for line in record:
            site = line.split()[0]
            by_site[site] = by_site.get(site, 0) + 1
        sites = ", ".join(f"{site} {count}" for site, count in sorted(by_site.items())) or "empty"
        print(f"download record {args.archive}: {len(record)} entries ({sites})")
        entries = read_never(args.file)
        print(f"never-keep list {args.file}: {len(entries)} entries")
        for creator, show in entries:
            print(f"   {creator} | {show}")


if __name__ == "__main__":
    main()
