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

VIDEO = {".mp4", ".mkv", ".m4v", ".avi", ".webm", ".mov"}
CONVENTIONAL = re.compile(r" - S\d{2}E\d{2}(?:-\d{2})?(?: - .+)?$")
FULLWIDTH = {"｜": "|", "：": ":", "⧸": "/", "／": "/", "×": "x", "＆": "&", "？": "?", "！": "!", "＂": '"', "＇": "'"}
NOISE = re.compile(r"\b(full\s*len(?:g)?th|unedited reaction|reaction|unedited|edited|finale|\[finale\])\b", re.I)
EPISODE_PATTERNS = [
    # S2 x E12-15 / S4 X E5-7 / S1 x E13-16
    re.compile(r"\bS(?P<s>\d{1,2})\s*[xX]\s*E(?P<e1>\d{1,3})(?:\s*-\s*E?(?P<e2>\d{1,3}))?\b"),
    # S01E05 / S01e08 / S02E3-4 / S03E11-E12
    re.compile(r"\bS(?P<s>\d{1,2})\s*E(?P<e1>\d{1,3})(?:\s*-\s*E?(?P<e2>\d{1,3}))?\b", re.I),
    # 2x9 / 1X08 / 4x15 / 2x3-4
    re.compile(r"\b(?P<s>\d{1,2})\s*[xX]\s*(?P<e1>\d{1,3})(?:\s*-\s*(?P<e2>\d{1,3}))?\b"),
    # Episode 3 / Ep 3 (season 1)
    re.compile(r"\b(?:Episodes?|Ep\.?)\s*(?P<e1>\d{1,3})(?:\s*-\s*(?P<e2>\d{1,3}))?\b", re.I),
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
FULL_LENGTH = re.compile(r"\bfull\s*len(?:g)?th\b|\bunedited\b", re.I)
SPECIAL_WORDS = re.compile(r"\b(movie|film|trailer|opening|ending|ova|special|recap|teaser)\b|\bop\s*/\s*ed\b|\+", re.I)


def normalize(text):
    for k, v in FULLWIDTH.items():
        text = text.replace(k, v)
    return unicodedata.normalize("NFKC", text)


def key(text):
    """Comparison key for show names: lower-case letters/digits only, no leading 'the'."""
    t = normalize(text).lower()
    t = re.sub(r"^the\s+", "", t)
    return re.sub(r"[^a-z0-9]", "", t)


def parse(filename):
    """-> dict(show_hint, season, e1, e2, special(bool), note) from a raw or semi-raw file name."""
    stem = normalize(Path(filename).stem)
    stem = re.sub(r"\s*\[\d{6,}\]\s*$", "", stem)            # Patreon post id
    if CONVENTIONAL.search(stem) and not re.search(r"E\d{2}-\d(?!\d)", stem):
        return None                                           # already conventional
    parts = [p.strip() for p in re.split(r"\s*\|\s*", stem) if p.strip()]
    m = None
    for pat in EPISODE_PATTERNS:
        m = pat.search(stem)
        if m:
            break
    if not m:
        m = next((b for b in (BARE_EPISODE.match(p) for p in parts[1:]) if b), None)
    # show hint: the nearest segment BEFORE the episode one that isn't noise ("EPISODE TITLE | SHOW | Reaction 2x11"
    # and "Full Length | SHOW | 2x11" both give SHOW), else the episode segment itself ("JJK 2x15"), else the rest
    ep_idx = next((i for i, p in enumerate(parts) if m and m.group(0) in p), None)
    order = list(range(len(parts))) if ep_idx is None else \
        list(range(ep_idx - 1, -1, -1)) + [ep_idx] + list(range(ep_idx + 1, len(parts)))
    hint = ""
    for i in order:
        p2 = parts[i].replace(m.group(0), "") if i == ep_idx else parts[i]
        p2 = NOISE.sub("", p2).strip(" -:")
        if p2:
            hint = p2
            break
    hint = re.split(r"\s*:\s*", hint)[0].strip()             # "Demon Slayer: Kimetsu no Yaiba" -> "Demon Slayer"
    if re.search(r"\blive[\s-]*action\b", stem, re.I) and not re.search(r"live[\s-]*action", hint, re.I):
        hint += " Live Action"                                # "One Piece | Live Action 2x1": not the anime
    hint = re.sub(r"\s+-\s*$", "", hint)
    if not m:
        return {"hint": hint, "special": True, "note": "no episode number (movie/trailer/opening?)"}
    if re.search(r"E\d+\s*\+\s*E?\d+", stem):
        return {"hint": hint, "special": True, "note": "non-contiguous episodes (e.g. 'E4 + E8')"}
    s = int(m.groupdict().get("s") or 1)
    end = stem.find(m.group(0)) + len(m.group(0))            # offsets in stem (a BARE match is per segment)
    sw = SEASON_WORD.search(stem[:end]) if not m.groupdict().get("s") else None
    if sw:
        n = sw.group("n").lower()
        s = WORD_NUMBERS.get(n) or int(n)
    e1 = int(m.group("e1"))
    e2 = int(m.group("e2")) if m.group("e2") else None
    if m.re is BARE_EPISODE and (m.group("more") or m.group("sep") == "&"):   # a list: must be consecutive
        nums = [int(n) for n in re.findall(r"\d+", m.group(0)[len(m.group("pre")):])]
        if nums != list(range(e1, e1 + len(nums))):
            return {"hint": hint, "special": True, "note": f"non-contiguous episodes ({', '.join(map(str, nums))})"}
        e2 = nums[-1] if len(nums) > 1 else None
    a = AND_EPISODE.match(stem[end:])
    if a and int(a.group("s") or s) == s:
        last, nxt = e2 or e1, int(a.group("e"))
        if nxt != last + 1:
            return {"hint": hint, "special": True, "note": f"non-contiguous episodes (E{last} & E{nxt})"}
        e2 = nxt
    rest = stem.replace(m.group(0), "", 1).replace(a.group(0), "", 1) if a else stem.replace(m.group(0), "", 1)
    special = bool(SPECIAL_WORDS.search(rest))
    if e2 is not None and e2 <= e1:
        return {"hint": hint, "special": True, "note": f"odd range E{e1}-{e2}"}
    return {"hint": hint, "season": s, "e1": e1, "e2": e2, "special": special,
            "note": "title has special-sounding words, check" if special else ""}


def is_full_length(title):
    """Posts marked as the full reaction ("Full Length", "Unedited"), not "Edited | ..." or short clip posts."""
    t = normalize(title)
    return bool(FULL_LENGTH.search(t)) and not re.match(r"\s*edited\b", t, re.I)


def library_index(root, aliases=None):
    """{key(show folder): [(creator, show_dir)]} plus the display name used inside each folder
    (learned from its conventional files; else the alias of the folder name, e.g. JJK -> Jujutsu Kaisen)."""
    aliases = aliases or {}
    idx, display = {}, {}
    for creator in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        for show in sorted(p for p in creator.iterdir() if p.is_dir()):
            idx.setdefault(key(show.name), []).append((creator.name, show))
            names = Counter()
            for f in show.rglob("*"):
                m = re.match(r"(.+?)\s+- S\d{2}E\d{2}", f.stem) if f.suffix.lower() in VIDEO else None
                if m:
                    names[m.group(1).strip()] += 1
            display[show] = names.most_common(1)[0][0] if names else aliases.get(key(show.name), show.name)
    return idx, display


def find_show(hint, idx, aliases, creator=None):
    """Folders matching the raw name OR its alias (JJK -> Creator C/JJK *and* Creator A/Jujutsu Kaisen),
    so a show that two creators react to is ambiguous (REVIEW / --creator) instead of guessed."""
    if not hint:
        return []
    keys = {key(hint), key(aliases.get(key(hint), hint))}
    cands = []
    for k in keys:
        hits = idx.get(k, [])
        if not hits:                                          # prefix match: "Haikyuu" vs folder "Haikyu"
            hits = [c for kk, v in idx.items() for c in v if kk and len(min(kk, k, key=len)) >= 4
                    and (kk.startswith(k) or k.startswith(kk))]
        cands += [c for c in hits if c not in cands]
    if creator:
        cands = [c for c in cands if c[0].lower() == creator.lower()]
    return cands


def episodes_present(show_dir):
    """{(season, episode)} covered by the conventional files already in a show folder (ranges expanded)."""
    have = set()
    for f in show_dir.rglob("*"):
        m = re.search(r" - S(\d{2})E(\d{2})(?:-E?(\d{2}))?", f.stem) if f.suffix.lower() in VIDEO else None
        if m:
            s, e1 = int(m[1]), int(m[2])
            have.update((s, e) for e in range(e1, int(m[3] or e1) + 1))
    return have


MOVIE_NOISE = re.compile(r"\b(full\s*len(?:g)?th|unedited|movie reaction|reaction|first time watching|first time|watching"
                         r"|react(s|ing)?|patreon exclusive|movie ticket pick)\b"
                         r"|\b(?:the\s+)?movie\s*$", re.I)   # "Violet Evergarden | The Movie"
# no episode number, but not a movie either
NOT_MOVIE = re.compile(r"\b(trailer|opening|ending|ova'?s?|recap|teaser|sbs|q\s*&\s*a|specials?|volume covers|"
                       r"animal theater|challenge|announcement|livestream|stream)\b|\bop\s*/\s*ed\b", re.I)


def movie_title(filename):
    """'50 First Dates (2004) ｜ MOVIE REACTION ｜ First Time Watching [123].mp4' -> '50 First Dates (2004)';
    'Full Length ｜ Haikyuu ｜ The Dumpster Battle' -> 'Haikyuu - The Dumpster Battle' (all non-noise segments)."""
    stem = re.sub(r"\s*\[\d+\]\s*$", "", normalize(Path(filename).stem))     # post id
    parts =[re.sub(r"\s+", " ", MOVIE_NOISE.sub("", p)).strip(" -:!") for p in re.split(r"\s*\|\s*", stem)]
    t = " - ".join(p for p in parts if p)
    return re.sub(r'\s*[<>:"/\\?*]\s*', " - ", t).strip(" -")   # Windows/SMB-safe


def is_movie(title, info):
    """A post/file with no episode number that isn't a trailer, OVA, special, ... ."""
    return info is not None and "season" not in info and info.get("note", "").startswith("no episode number") \
        and not NOT_MOVIE.search(normalize(title)) \
        and bool(movie_title(title + ".mp4"))


def movie_present(movies_dir, title):
    """The file in <creator>/Movies with the same title (years ignored), else None."""
    want = key(re.sub(r"\(\d{4}\)", "", title))
    if not Path(movies_dir).is_dir():
        return None
    return next((p for p in Path(movies_dir).iterdir() if p.is_file()
                 and key(re.sub(r"\(\d{4}\)|,\s*\d{4}$", "", p.stem)) == want), None)


def target_for(info, show_dir, display, ext):
    season_dir = show_dir / f"Season {info['season']:02d}"
    has_seasons = show_dir.is_dir() and any(p.is_dir() and re.match(r"Season \d+", p.name) for p in show_dir.iterdir())
    folder = season_dir if has_seasons else show_dir
    ep = f"S{info['season']:02d}E{info['e1']:02d}" + (f"-{info['e2']:02d}" if info["e2"] else "")
    return folder / f"{display[show_dir]} - {ep}{ext}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="library root, e.g. \\\\nas\\media\\reaction")
    ap.add_argument("--src", help="folder with new downloads (import mode)")
    ap.add_argument("--tidy", action="store_true", help="rename non-conventional files inside the library")
    ap.add_argument("--creator", help="only consider this creator (for shows that exist under several)")
    local = Path(__file__).with_name("reaction-aliases.json")          # your own (git-ignored), else the example
    ap.add_argument("--aliases", default=str(local if local.exists() else local.with_suffix(".example.json")),
                    help="show-name aliases JSON (default: reaction-aliases.json, else reaction-aliases.example.json)")
    ap.add_argument("--apply", action="store_true", help="really move/rename (default: dry run)")
    ap.add_argument("--keep", action="store_true", help="import mode: copy, keep the source file")
    ap.add_argument("--new-shows", action="store_true",
                    help="import mode: create <creator>/<show>/ for shows the library doesn't have yet")
    a = ap.parse_args()
    if bool(a.src) == bool(a.tidy):
        sys.exit("use exactly one of --src (import downloads) or --tidy (rename inside the library)")
    aliases = {key(k): v for k, v in json.loads(Path(a.aliases).read_text(encoding="utf-8")).items()} \
        if Path(a.aliases).exists() else {}
    idx, display = library_index(a.root, aliases)

    creators = {c.name.lower(): c.name for c in Path(a.root).iterdir() if c.is_dir()}
    if a.src:
        # downloads may sit in per-creator folders (yt-dlp -o "%(uploader)s/..."): the folder names the creator
        files = [p for p in Path(a.src).rglob("*") if p.is_file() and p.suffix.lower() in VIDEO]
    else:
        files = [p for show in display for p in show.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO]
    conventional_shows = {s for s in display if any(CONVENTIONAL.search(p.stem) for p in s.rglob("*"))}

    plan, counts = [], Counter()
    for f in sorted(files):
        info = parse(f.name)
        if info is None:
            if a.src:
                counts["review"] += 1
                plan.append(("REVIEW", f, None, "already conventional name, but in the download folder: which show?"))
            continue
        if a.tidy:
            show_dir = next(s for s in display if s in f.parents)
            if "season" not in info and show_dir not in conventional_shows:
                counts["left"] += 1                           # movie folders (no episodes at all): left as they are
                continue
            cands, creator = [(show_dir.parent.name, show_dir)], show_dir.parent.name
        else:
            # the inbox sub-folder names the creator (patreon_download.ps1 -Creator), even one new to the library
            folder_creator = (creators.get(f.parent.name.lower(), f.parent.name)
                              if f.parent != Path(a.src) else None)
            creator = creators.get((a.creator or "").lower(), a.creator) or folder_creator
            cands = find_show(info["hint"], idx, aliases, creator)
        if info.get("special") and "season" not in info:
            movies = Path(a.root, creator, "Movies") if a.src and creator else None
            # creators with a Movies folder (or --new-shows, which creates it); trailers, OVAs, ... stay REVIEW
            if movies and (movies.is_dir() or a.new_shows) and is_movie(f.stem, info):
                title = movie_title(f.name)
                tgt = movies / f"{title}{f.suffix.lower()}"
                same = movie_present(movies, title)
                if same:
                    counts["skip"] += 1
                    plan.append(("SKIP", f, same, "movie already there"))
                else:
                    counts["move"] += 1
                    plan.append(("MOVE", f, tgt, "movie (title from the post; check it)"))
                continue
            counts["review"] += 1
            plan.append(("REVIEW", f, None, f"{info['note']}; show hint '{info['hint']}'"))
            continue
        if not cands and a.src and creator and a.new_shows and info["hint"]:
            new_dir = Path(a.root, creator, aliases.get(key(info["hint"]), info["hint"]))
            display.setdefault(new_dir, new_dir.name)
            cands = [(creator, new_dir)]
        if len(cands) != 1:
            counts["review"] += 1
            if not cands:
                why = ("new show for this creator: re-run with --new-shows to create its folder" if creator
                       else "no matching show folder: add an alias, --creator, or download per creator")
            else:
                why = "show exists under " + ", ".join(c[0] for c in cands) + ": use --creator or per-creator folders"
            plan.append(("REVIEW", f, None, f"{why} (hint '{info['hint']}')"))
            continue
        tgt = target_for(info, cands[0][1], display, f.suffix.lower())
        wanted = {(info["season"], e) for e in range(info["e1"], (info["e2"] or info["e1"]) + 1)}
        have = episodes_present(cands[0][1]) if a.src and cands[0][1].is_dir() else set()
        overlap, missing = sorted(wanted & have), sorted(wanted - have)
        if a.src and overlap and not missing:
            counts["skip"] += 1
            plan.append(("SKIP", f, tgt, "already have " + ", ".join(f"S{s:02d}E{e:02d}" for s, e in overlap)
                         + " (other files); delete the download if it's the same reaction"))
            continue
        if a.src and overlap:
            counts["review"] += 1
            plan.append(("REVIEW", f, tgt, "partly there already: has " + ", ".join(f"E{e:02d}" for _, e in overlap)
                         + "; missing " + ", ".join(f"E{e:02d}" for _, e in missing)))
            continue
        if info.get("special"):
            counts["review"] += 1
            plan.append(("REVIEW", f, tgt, info["note"]))
        elif tgt.exists() and tgt.resolve() != f.resolve():
            counts["skip"] += 1
            plan.append(("SKIP", f, tgt, f"target exists ({f.stat().st_size / 2**20:.0f} MiB new vs {tgt.stat().st_size / 2**20:.0f} MiB there)"))
        else:
            counts["move"] += 1
            plan.append(("MOVE" if a.src else "RENAME", f, tgt, ""))

    for action, f, tgt, why in plan:
        rel = os.path.relpath(tgt, a.root) if tgt else ""
        print(f"{action:7} {f.name}\n        -> {rel}{('   # ' + why) if why else ''}")
    left = f", {counts['left']} in movie folders left as they are" if counts["left"] else ""
    print(f"\n{counts['move']} to {'move' if a.src else 'rename'}, {counts['skip']} already there, {counts['review']} to review{left}"
          f"{'' if a.apply else '   (dry run: add --apply)'}")
    if not a.apply:
        return
    for action, f, tgt, _ in plan:
        if action not in ("MOVE", "RENAME"):
            continue
        tgt.parent.mkdir(parents=True, exist_ok=True)
        if a.src and a.keep:
            shutil.copy2(f, tgt)
        else:
            shutil.move(str(f), str(tgt))
        print("done", tgt.name)


if __name__ == "__main__":
    main()
