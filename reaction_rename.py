#!/usr/bin/env python3
"""Rename reaction videos (Patreon downloads) to the library's Plex/Jellyfin convention and file them.

Library layout (Plex/Jellyfin style):
    <root>/<Creator>/<Show folder>/[Season NN/]<Show> - S01E08[-09][ - Title].ext

Two modes, both a DRY RUN unless --apply:
  * Import downloads:   reaction_rename.py --root "\\\\nas\\media\\reaction" --src C:\\github\\PatreonHelper
  * Tidy the library:   reaction_rename.py --root "\\\\nas\\media\\reaction" --tidy
    (renames the not-yet-conventional files inside each show folder)

How a file is understood:
  * full-width punctuation from Patreon titles is normalized (｜ ： ⧸ × …), " [123456789]" post ids and
    "Full Length" / "Unedited Reaction" noise are dropped;
  * the episode comes from S1 x E5-8 / S01E05-08 / S01e08 / 2x9 / 1X08 / "Episode 3" (season 1);
  * the show is matched to an existing show folder (aliases in reaction-aliases.json, then fuzzy name match);
    the creator is the one that has that folder; ambiguous (show under two creators) needs --creator;
  * the display name comes from the folder's existing files ("Haikyuu - S.." in folder "Haikyu"), so new
    files match what you already have; season sub-folders are used when the show folder has them.
Anything it can't place safely (movies, trailers, openings, "E4 + E8" style ranges, unknown shows) is listed
as REVIEW and never touched. Existing targets are never overwritten (SKIP, with both sizes shown).
"""
import argparse
import json
import os
import re
import shutil
import sys
import unicodedata
from collections import Counter
from pathlib import Path


# ======================================================================================================
# Patterns and constants
# ======================================================================================================

VIDEO = {".mp4", ".mkv", ".m4v", ".avi", ".webm", ".mov"}

# a file name already in library style: "Show - S01E08", "Show - S01E08-09", "Show - S01E08 - Title"
CONVENTIONAL = re.compile(r" - S\d{2}E\d{2}(?:-\d{2})?(?: - .+)?$")

# Patreon titles use full-width look-alikes of ASCII punctuation
FULLWIDTH = {"｜": "|", "：": ":", "⧸": "/", "／": "/", "×": "x", "＆": "&", "？": "?", "！": "!", "＂": '"', "＇": "'"}

# words in a title that are not part of the show name
NOISE = re.compile(r"\b(full\s*len(?:g)?th|unedited reaction|reaction|unedited|edited|finale|\[finale\])\b", re.I)

# How an episode is written in a title, most specific first (the first pattern that matches wins)
EPISODE_PATTERNS = [
    # S2 x E12-15 / S4 X E5-7 / S1 x E13-16
    re.compile(r"\bS(?P<s>\d{1,2})\s*[xX]\s*E(?P<e1>\d{1,3})(?:\s*-\s*E?(?P<e2>\d{1,3}))?\b"),
    # S01E05 / S01e08 / S02E3-4 / S03E11-E12
    re.compile(r"\bS(?P<s>\d{1,2})\s*E(?P<e1>\d{1,3})(?:\s*-\s*E?(?P<e2>\d{1,3}))?\b", re.I),
    # 2x9 / 1X08 / 4x15 / 2x3-4
    re.compile(r"\b(?P<s>\d{1,2})\s*[xX]\s*(?P<e1>\d{1,3})(?:\s*-\s*(?P<e2>\d{1,3}))?\b"),
    # Episode 3 / Ep 3 (season 1)
    re.compile(r"\b(?:Episodes?|Eps?\.?)\s*(?P<e1>\d{1,3})(?:\s*-\s*(?P<e2>\d{1,3}))?\b", re.I),
]

# a segment that is only an (absolute) episode number: "| One Piece | 898 & 899", "| ONE PIECE | Reaction 612 & 613",
# "| One Piece | 869 - 871", "| One Piece | 234, 235, 236"
BARE_EPISODE = re.compile(r"^(?P<pre>(?:reaction\s+)?(?:(?:season|book)\s*(?:\d{1,2}|one|two|three|four|five|six)\s*:?\s*)?)"
                          r"(?P<e1>\d{1,4})(?P<more>(?:\s*,\s*\d{1,4})*)"
                          r"(?:\s*,?\s*(?P<sep>[&-])\s*(?P<e2>\d{1,4}))?$", re.I)

# one more episode joined with "&" / "+": "2x5 & 2x6", "3x1 & 3x2", "Episodes 1 + 2"; "8-10 + 12" is non-contiguous
AND_EPISODE = re.compile(r"^\s*[&+]\s*(?:(?P<s>\d{1,2})\s*[xX]\s*)?(?P<e>\d{1,3})\b")

# season given in words before "Episodes N-M": "Season 2 Episodes 1-4", "Book Two: Episodes 5-8" (Avatar)
SEASON_WORD = re.compile(r"\b(?:Season|Book)\s*(?P<n>\d{1,2}|one|two|three|four|five|six)\b", re.I)
WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

# a single trailing digit on the show name is the season when nothing else says one ("Stranger Things 4 | Ep. 3");
# not after "No." / "Part" / ... ("Kaiju No. 8 | Ep. 3"), and never 1 (season 1 is written without a number)
SEASON_SUFFIX = re.compile(r"\b(?P<prev>[A-Za-z']+\.?)\s+(?P<n>[2-9])$")
SEASON_SUFFIX_STOP = {"no", "no.", "part", "pt", "pt.", "vol", "vol.", "volume", "chapter", "book", "season", "s", "ep", "ep.", "episode"}

FULL_LENGTH = re.compile(r"\bfull\s*len(?:g)?th\b|\bunedited\b|\buncut\b", re.I)
CUT_VERSION = re.compile(r"\bcut\b", re.I)   # "(Cut Reaction)", "CUT VERSION": the edited one; \b keeps "Uncut" out
SPECIAL_WORDS = re.compile(r"\b(movie|film|trailer|opening|ending|ova|special|recap|teaser)\b|\bop\s*/\s*ed\b|\+", re.I)

# movie titles: words that are not part of the title
MOVIE_NOISE = re.compile(r"\b(full\s*len(?:g)?th|unedited|full\s*movie(?:\s*reaction)?|movie reaction|reaction|first time watching|first time|watching"
                         r"|react(s|ing)?|patreon exclusive|movie ticket pick)\b"
                         r"|\b(?:the\s+)?movie\s*$", re.I)   # "Violet Evergarden | The Movie"
# no episode number, but not a movie either
NOT_MOVIE = re.compile(r"\b(trailer|opening|ending|ova'?s?|recap|teaser|sbs|q\s*&\s*a|specials?|volume covers|"
                       r"animal theater|challenge|announcement|livestream|stream|behind the scenes|bts|movie night|update)\b|\bop\s*/\s*ed\b", re.I)


# ======================================================================================================
# Reading names
# ======================================================================================================

def normalize(text):
    """Full-width punctuation to ASCII, then Unicode NFKC."""
    for fullwidth, ascii_char in FULLWIDTH.items():
        text = text.replace(fullwidth, ascii_char)
    return unicodedata.normalize("NFKC", text)


def key(text):
    """Comparison key for show names: lower-case letters/digits only, no leading 'the'."""
    lowered = normalize(text).lower()
    without_the = re.sub(r"^the\s+", "", lowered)
    return re.sub(r"[^a-z0-9]", "", without_the)


def clean_hint(hint):
    """Drop what's left of the episode part in one-segment titles ("andor season 2 episode 1 [full length]",
    "the acolyte s1 e1+2 [full length]"): season words, 's1', 'episode(s)/ep(s)', '+2', empty brackets."""
    cleaned = re.sub(r"\b(?:season|book)\s*(?:\d{1,2}|one|two|three|four|five|six)\b", " ", hint, flags=re.I)
    cleaned = re.sub(r"\bs\d{1,2}\b|\b(?:episodes?|eps?)\b\.?", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*[&+]\s*e?\d+\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"[\[\(]\s*[\]\)]|[\[\]]", " ", cleaned)            # "[]" left by "[full length]", a lone "["
    return re.sub(r"\s+", " ", cleaned).strip(" -:+&|")


def pretty(name):
    """Folder name for a new show: all-lowercase post titles ("the bad batch") get capitalized words."""
    if name != name.lower():
        return name
    return " ".join(word[:1].upper() + word[1:] for word in name.split(" "))


def parse(filename):
    """-> dict(show_hint, season, e1, e2, special(bool), note) from a raw or semi-raw file name."""
    # ---- 1. clean the name; a name already in library style needs no parsing ----
    stem = normalize(Path(filename).stem)
    stem = re.sub(r"\s*\[\d{6,}\]\s*$", "", stem)            # Patreon post id

    # a range end written with one digit ("E01-2") is not the library's two-digit form, so such a name is parsed anyway
    looks_conventional = CONVENTIONAL.search(stem) and not re.search(r"E\d{2}-\d(?!\d)", stem)
    if looks_conventional:
        return None                                           # already conventional

    # ---- 2. find the episode marker (the first pattern that matches wins) ----
    segments = [segment.strip() for segment in re.split(r"\s*\|\s*", stem) if segment.strip()]
    match = None
    for pattern in EPISODE_PATTERNS:
        match = pattern.search(stem)
        if match:
            break
    if not match:
        # no "2x9" style marker: a later segment that is only a number ("| One Piece | 898 & 899")
        bare_matches = (BARE_EPISODE.match(segment) for segment in segments[1:])
        match = next((bare for bare in bare_matches if bare), None)

    # ---- 3. the show hint ----
    # the nearest segment BEFORE the episode one that isn't noise ("EPISODE TITLE | SHOW | Reaction 2x11"
    # and "Full Length | SHOW | 2x11" both give SHOW), else the episode segment itself ("JJK 2x15"), else the rest
    episode_segment = next((i for i, segment in enumerate(segments) if match and match.group(0) in segment), None)
    if episode_segment is None:
        search_order = list(range(len(segments)))
    else:
        segments_before = list(range(episode_segment - 1, -1, -1))     # nearest first
        segments_after = list(range(episode_segment + 1, len(segments)))
        search_order = segments_before + [episode_segment] + segments_after

    hint = ""
    for i in search_order:
        if i == episode_segment:
            # "The Office S1 E1 - Pilot (Uncut Version)": the show is what comes BEFORE the episode number; what
            # follows is the episode's title. Only when nothing usable precedes it ("2x12 Korra Reaction!") the rest counts.
            marker_at = segments[i].find(match.group(0))
            text_before_marker = clean_hint(NOISE.sub("", segments[i][:marker_at]).strip(" -:"))
            candidate = text_before_marker if text_before_marker else segments[i].replace(match.group(0), "")
        else:
            candidate = segments[i]
        candidate = clean_hint(NOISE.sub("", candidate).strip(" -:"))   # "Season 4" alone is not a show ("Show | Season 4 | Ep. 3")
        if candidate:
            hint = candidate
            break

    hint = re.split(r"\s*:\s*", hint)[0].strip()             # "Demon Slayer: Kimetsu no Yaiba" -> "Demon Slayer"
    hint = re.split(r'\s*[,"“”]', hint)[0].strip()           # "The Owl House 2x9 Reaction, "Eclipse Lake"" -> "The Owl House"; 'Attack on Titan "Hero"' -> 'Attack on Titan'

    title_says_live_action = re.search(r"\blive[\s-]*action\b", stem, re.I)
    hint_says_live_action = re.search(r"live[\s-]*action", hint, re.I)
    if title_says_live_action and not hint_says_live_action:
        hint += " Live Action"                                # "One Piece | Live Action 2x1": not the anime
    hint = clean_hint(hint)

    # ---- 4. things that can't be placed: no episode, or episodes that don't run in order ----
    if not match:
        return {"hint": hint, "special": True, "note": "no episode number (movie/trailer/opening?)"}
    if re.search(r"E\d+\s*\+\s*E?\d+", stem):
        return {"hint": hint, "special": True, "note": "non-contiguous episodes (e.g. 'E4 + E8')"}

    # ---- 5. the season ----
    groups = match.groupdict()
    season = int(groups.get("s") or 1)
    has_season_group = bool(groups.get("s"))
    end = stem.find(match.group(0)) + len(match.group(0))     # offsets in stem (a BARE match is per segment)

    season_word = None if has_season_group else SEASON_WORD.search(stem[:end])
    if season_word:
        number_text = season_word.group("n").lower()
        season = WORD_NUMBERS.get(number_text) or int(number_text)
    elif not has_season_group:
        trailing_season = SEASON_SUFFIX.search(hint)          # "Stranger Things 4 | Ep. 3": season 4 of Stranger Things
        if trailing_season and trailing_season.group("prev").lower() not in SEASON_SUFFIX_STOP:
            season = int(trailing_season.group("n"))
            hint = hint[:trailing_season.start("n")].rstrip()

    # ---- 6. the episode numbers ----
    e1 = int(match.group("e1"))
    e2 = int(match.group("e2")) if match.group("e2") else None

    is_bare_list = match.re is BARE_EPISODE and (match.group("more") or match.group("sep") == "&")
    if is_bare_list:                                          # "234, 235, 236" or "898 & 899": must be consecutive
        listed_text = match.group(0)[len(match.group("pre")):]
        listed_numbers = [int(n) for n in re.findall(r"\d+", listed_text)]
        if listed_numbers != list(range(e1, e1 + len(listed_numbers))):
            return {"hint": hint, "special": True,
                    "note": f"non-contiguous episodes ({', '.join(map(str, listed_numbers))})"}
        e2 = listed_numbers[-1] if len(listed_numbers) > 1 else None

    # "2x5 & 2x6": one more episode joined on after the marker
    and_match = AND_EPISODE.match(stem[end:])
    if and_match and int(and_match.group("s") or season) == season:
        last_so_far = e2 or e1
        next_episode = int(and_match.group("e"))
        if next_episode != last_so_far + 1:
            return {"hint": hint, "special": True, "note": f"non-contiguous episodes (E{last_so_far} & E{next_episode})"}
        e2 = next_episode

    # ---- 7. special-sounding words in the rest of the title (movie, trailer, ova ...) ----
    rest = stem.replace(match.group(0), "", 1)
    if and_match:
        rest = rest.replace(and_match.group(0), "", 1)
    special = bool(SPECIAL_WORDS.search(rest))

    if e2 is not None and e2 <= e1:
        return {"hint": hint, "special": True, "note": f"odd range E{e1}-{e2}"}
    return {"hint": hint, "season": season, "e1": e1, "e2": e2, "special": special,
            "note": "title has special-sounding words, check" if special else ""}


def is_full_length(title):
    """Posts marked as the full reaction ("Full Length", "Unedited", "Uncut"), not "Edited | ...", "(Cut Reaction)"
    or short clip posts. Creators that post both: Uncut = full, Cut = edited."""
    normalized = normalize(title)
    if re.match(r"\s*edited\b", normalized, re.I) or CUT_VERSION.search(normalized):
        return False
    return bool(FULL_LENGTH.search(normalized))


# ======================================================================================================
# Reading the library
# ======================================================================================================

def library_index(root, aliases=None):
    """{key(show folder): [(creator, show_dir)]} plus the display name used inside each folder
    (learned from its conventional files; else the alias of the folder name, e.g. JJK -> Jujutsu Kaisen)."""
    aliases = aliases or {}
    idx, display = {}, {}

    for creator in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        for show in sorted(p for p in creator.iterdir() if p.is_dir()):
            idx.setdefault(key(show.name), []).append((creator.name, show))

            # the show's name as its existing files spell it: the most common "<name> - S01E01" prefix
            name_counts = Counter()
            for file in show.rglob("*"):
                is_video = file.suffix.lower() in VIDEO
                name_match = re.match(r"(.+?)\s+- S\d{2}E\d{2}", file.stem) if is_video else None
                if name_match:
                    name_counts[name_match.group(1).strip()] += 1

            if name_counts:
                display[show] = name_counts.most_common(1)[0][0]
            else:
                display[show] = aliases.get(key(show.name), show.name)

    return idx, display


def find_show(hint, idx, aliases, creator=None):
    """Folders matching the raw name OR its alias (JJK -> Creator C/JJK *and* Creator A/Jujutsu Kaisen),
    so a show that two creators react to is ambiguous (REVIEW / --creator) instead of guessed."""
    if not hint:
        return []

    # the raw name, its alias, and every other name whose alias is the same show: a hint "Jujutsu Kaisen" (from a
    # Patreon collection) must find the folder "JJK" when the aliases say JJK -> Jujutsu Kaisen
    canon = key(aliases.get(key(hint), hint))
    keys = {key(hint), canon} | {k for k, v in aliases.items() if key(v) == canon}

    candidates = []
    for k in keys:
        hits = idx.get(k, [])
        if not hits:                                          # prefix match: "Haikyuu" vs folder "Haikyu"
            hits = []
            for folder_key, folders in idx.items():
                shorter_key = min(folder_key, k, key=len)
                is_prefix_match = folder_key.startswith(k) or k.startswith(folder_key)
                if folder_key and len(shorter_key) >= 4 and is_prefix_match:    # under 4 letters is too loose
                    hits += folders
        candidates += [hit for hit in hits if hit not in candidates]

    if creator:
        candidates = [c for c in candidates if c[0].lower() == creator.lower()]
    return candidates


def episodes_present(show_dir):
    """{(season, episode)} covered by the conventional files already in a show folder (ranges expanded)."""
    have = set()
    for file in show_dir.rglob("*"):
        is_video = file.suffix.lower() in VIDEO
        episode_match = re.search(r" - S(\d{2})E(\d{2})(?:-E?(\d{2}))?", file.stem) if is_video else None
        if episode_match:
            season, first = int(episode_match[1]), int(episode_match[2])
            last = int(episode_match[3] or first)
            have.update((season, episode) for episode in range(first, last + 1))
    return have


# ======================================================================================================
# Movies
# ======================================================================================================

def movie_title(filename):
    """'50 First Dates (2004) ｜ MOVIE REACTION ｜ First Time Watching [123].mp4' -> '50 First Dates (2004)';
    'Full Length ｜ Haikyuu ｜ The Dumpster Battle' -> 'Haikyuu - The Dumpster Battle' (all non-noise segments)."""
    stem = re.sub(r"\s*\[\d+\]\s*$", "", normalize(Path(filename).stem))     # post id

    # drop the noise words from each "|" segment
    segments = [re.sub(r"\s+", " ", MOVIE_NOISE.sub("", segment)).strip(" -:!")
                for segment in re.split(r"\s*\|\s*", stem)]
    # drop the empty "[]" / "()" that "[full length]" leaves behind
    segments = [re.sub(r"\s+", " ", re.sub(r"[\[\(]\s*[\]\)]", "", segment)).strip(" -:!") for segment in segments]

    title = pretty(" - ".join(segment for segment in segments if segment))
    return re.sub(r'\s*[<>:"/\\?*]\s*', " - ", title).strip(" -")   # Windows/SMB-safe


def is_movie(title, info):
    """A post/file with no episode number that isn't a trailer, OVA, special, ... ."""
    if info is None or "season" in info:
        return False
    if not info.get("note", "").startswith("no episode number"):
        return False
    if NOT_MOVIE.search(normalize(title)):
        return False
    return bool(movie_title(title + ".mp4"))


def movie_present(movies_dir, title):
    """The file in <creator>/Movies with the same title (years ignored), else None."""
    wanted_key = key(re.sub(r"\(\d{4}\)", "", title))
    if not Path(movies_dir).is_dir():
        return None

    for path in Path(movies_dir).iterdir():
        if not path.is_file():
            continue
        # "(2014)" and a trailing ", 2014" both count as the year
        stem_without_year = re.sub(r"\(\d{4}\)|,\s*\d{4}$", "", path.stem)
        if key(stem_without_year) == wanted_key:
            return path
    return None


# ======================================================================================================
# Where a file goes
# ======================================================================================================

def target_for(info, show_dir, display, ext):
    """The library path for a parsed episode: <show>[/Season NN]/<display name> - S01E08[-09].ext"""
    season_dir = show_dir / f"Season {info['season']:02d}"
    has_season_folders = show_dir.is_dir() and any(p.is_dir() and re.match(r"Season \d+", p.name) for p in show_dir.iterdir())
    folder = season_dir if has_season_folders else show_dir

    episode_label = f"S{info['season']:02d}E{info['e1']:02d}"
    if info["e2"]:
        episode_label += f"-{info['e2']:02d}"
    return folder / f"{display[show_dir]} - {episode_label}{ext}"


# ======================================================================================================
# Command line
# ======================================================================================================

def main():
    # ---- 1. arguments ----
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="library root, e.g. \\\\nas\\media\\reaction")
    parser.add_argument("--src", help="folder with new downloads (import mode)")
    parser.add_argument("--tidy", action="store_true", help="rename non-conventional files inside the library")
    parser.add_argument("--creator", help="only consider this creator (for shows that exist under several)")
    local_aliases = Path(__file__).with_name("reaction-aliases.json")          # your own (git-ignored), else the example
    parser.add_argument("--aliases", default=str(local_aliases if local_aliases.exists() else local_aliases.with_suffix(".example.json")),
                        help="show-name aliases JSON (default: reaction-aliases.json, else reaction-aliases.example.json)")
    parser.add_argument("--apply", action="store_true", help="really move/rename (default: dry run)")
    parser.add_argument("--keep", action="store_true", help="import mode: copy, keep the source file")
    parser.add_argument("--new-shows", action="store_true",
                        help="import mode: create <creator>/<show>/ for shows the library doesn't have yet")
    args = parser.parse_args()
    if bool(args.src) == bool(args.tidy):
        sys.exit("use exactly one of --src (import downloads) or --tidy (rename inside the library)")

    # ---- 2. aliases and the library's current contents ----
    alias_path = Path(args.aliases)
    if alias_path.exists():
        raw_aliases = json.loads(alias_path.read_text(encoding="utf-8"))
        aliases = {key(name): show for name, show in raw_aliases.items()}
    else:
        aliases = {}
    idx, display = library_index(args.root, aliases)

    # ---- 3. the files to look at ----
    creators = {c.name.lower(): c.name for c in Path(args.root).iterdir() if c.is_dir()}
    if args.src:
        # downloads may sit in per-creator folders (yt-dlp -o "%(uploader)s/..."): the folder names the creator
        files = [p for p in Path(args.src).rglob("*") if p.is_file() and p.suffix.lower() in VIDEO]
    else:
        files = [p for show in display for p in show.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO]

    # show folders that already have episode-style files (the others, e.g. movie folders, are left alone by --tidy)
    conventional_shows = {show for show in display if any(CONVENTIONAL.search(p.stem) for p in show.rglob("*"))}

    # ---- 4. decide what happens to each file ----
    plan = []                                                 # (action, file, target, why)
    counts = Counter()
    new_dirs = {}                                             # (creator, show key) -> folder created this run

    for video in sorted(files):
        info = parse(video.name)

        # -- 4a. already a conventional name --
        if info is None:
            if args.src:
                counts["review"] += 1
                plan.append(("REVIEW", video, None, "already conventional name, but in the download folder: which show?"))
            continue

        # -- 4b. which creator and which show folders could this be? --
        if args.tidy:
            show_dir = next(show for show in display if show in video.parents)
            if "season" not in info and show_dir not in conventional_shows:
                counts["left"] += 1                           # movie folders (no episodes at all): left as they are
                continue
            candidates, creator = [(show_dir.parent.name, show_dir)], show_dir.parent.name
        else:
            # the inbox sub-folder names the creator (patreon_download.ps1 -Creator), even one new to the library
            if video.parent != Path(args.src):
                folder_creator = creators.get(video.parent.name.lower(), video.parent.name)
            else:
                folder_creator = None
            creator = creators.get((args.creator or "").lower(), args.creator) or folder_creator
            candidates = find_show(info["hint"], idx, aliases, creator)

        # -- 4c. no episode number: a movie for the creator's Movies folder, else REVIEW --
        if info.get("special") and "season" not in info:
            movies_dir = Path(args.root, creator, "Movies") if args.src and creator else None
            # creators with a Movies folder (or --new-shows, which creates it); trailers, OVAs, ... stay REVIEW
            if movies_dir and (movies_dir.is_dir() or args.new_shows) and is_movie(video.stem, info):
                title = movie_title(video.name)
                target = movies_dir / f"{title}{video.suffix.lower()}"
                already_there = movie_present(movies_dir, title)
                if already_there:
                    counts["skip"] += 1
                    plan.append(("SKIP", video, already_there, "movie already there"))
                else:
                    counts["move"] += 1
                    plan.append(("MOVE", video, target, "movie (title from the post; check it)"))
                continue
            counts["review"] += 1
            plan.append(("REVIEW", video, None, f"{info['note']}; show hint '{info['hint']}'"))
            continue

        # -- 4d. --new-shows: a show the library doesn't have yet gets a folder --
        if not candidates and args.src and creator and args.new_shows and info["hint"]:
            name = aliases.get(key(info["hint"]), info["hint"])
            # one folder per show even when titles vary ("x-men '97" / "xmen 97"): the first spelling seen wins
            new_dir = new_dirs.setdefault((creator.lower(), key(name)), Path(args.root, creator, pretty(name)))
            display.setdefault(new_dir, new_dir.name)
            candidates = [(creator, new_dir)]

        # -- 4e. exactly one show folder is needed, otherwise REVIEW --
        if len(candidates) != 1:
            counts["review"] += 1
            if not candidates:
                if creator:
                    why = "new show for this creator: re-run with --new-shows to create its folder"
                else:
                    why = "no matching show folder: add an alias, --creator, or download per creator"
            else:
                why = "show exists under " + ", ".join(c[0] for c in candidates) + ": use --creator or per-creator folders"
            plan.append(("REVIEW", video, None, f"{why} (hint '{info['hint']}')"))
            continue

        # -- 4f. the target path, and which of the episodes are already in the library --
        show_dir = candidates[0][1]
        target = target_for(info, show_dir, display, video.suffix.lower())

        last_episode = info["e2"] or info["e1"]
        wanted = {(info["season"], e) for e in range(info["e1"], last_episode + 1)}
        have = episodes_present(show_dir) if args.src and show_dir.is_dir() else set()
        overlap = sorted(wanted & have)
        not_yet_there = sorted(wanted - have)

        # all of its episodes are already there (under other file names)
        if args.src and overlap and not not_yet_there:
            counts["skip"] += 1
            have_list = ", ".join(f"S{s:02d}E{e:02d}" for s, e in overlap)
            plan.append(("SKIP", video, target, f"already have {have_list} (other files); delete the download if it's the same reaction"))
            continue

        # only some of its episodes are there: a person decides
        if args.src and overlap:
            counts["review"] += 1
            has_list = ", ".join(f"E{e:02d}" for _, e in overlap)
            missing_list = ", ".join(f"E{e:02d}" for _, e in not_yet_there)
            plan.append(("REVIEW", video, target, f"partly there already: has {has_list}; missing {missing_list}"))
            continue

        # -- 4g. the ordinary outcomes --
        if info.get("special"):
            counts["review"] += 1
            plan.append(("REVIEW", video, target, info["note"]))
        elif target.exists() and target.resolve() != video.resolve():
            counts["skip"] += 1
            new_mib = video.stat().st_size / 2**20
            there_mib = target.stat().st_size / 2**20
            plan.append(("SKIP", video, target, f"target exists ({new_mib:.0f} MiB new vs {there_mib:.0f} MiB there)"))
        else:
            counts["move"] += 1
            plan.append(("MOVE" if args.src else "RENAME", video, target, ""))

    # ---- 5. print the plan and a summary ----
    for action, video, target, why in plan:
        relative_target = os.path.relpath(target, args.root) if target else ""
        why_comment = f"   # {why}" if why else ""
        print(f"{action:7} {video.name}\n        -> {relative_target}{why_comment}")

    left_note = f", {counts['left']} in movie folders left as they are" if counts["left"] else ""
    verb = "move" if args.src else "rename"
    dry_run_note = "" if args.apply else "   (dry run: add --apply)"
    print(f"\n{counts['move']} to {verb}, {counts['skip']} already there, {counts['review']} to review{left_note}{dry_run_note}")
    if not args.apply:
        return

    # ---- 6. --apply: do the moves and renames ----
    for action, video, target, _ in plan:
        if action not in ("MOVE", "RENAME"):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if args.src and args.keep:
            shutil.copy2(video, target)
        else:
            shutil.move(str(video), str(target))
        print("done", target.name)


if __name__ == "__main__":
    main()
