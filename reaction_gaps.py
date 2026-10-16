#!/usr/bin/env python3
"""Find the gaps in your reaction library before downloading: which of a creator's posts you already have,
which are missing, and which are only partly there.

Why: library files are renamed (no Patreon post id left), so a plain "download the whole creator" run would
re-download everything you already own. This lists the creator's posts (titles only, nothing downloaded),
matches every title against the library with reaction_rename's parser, and writes:
  * <out>-missing.txt   post URLs to download:  .\\Download-Creator.ps1 -Creator "<Creator>" -ListFile <out>-missing.txt
  * a report per show   have / missing / partial / new show / not an episode (movies, trailers, ...)
  * optionally (--seed-archive) "patreon <id>" lines for the posts you already have into yt-dlp's download
    archive, so later full-creator runs skip them by themselves.

Usage (dev PC, Firefox logged in to Patreon):
  python reaction_gaps.py --root "\\\\nas\\media\\reaction" --creator "Some Creator" --url https://www.patreon.com/c/<name>/posts
  python reaction_gaps.py ... --list-file C:\\patreon\\show_clean.txt          # a collection's URL list instead
  python reaction_gaps.py ... --from-tsv posts.tsv                              # reuse a saved listing (no network)
  python reaction_gaps.py ... --show "Vinland Saga" --seed-archive C:\\patreon\\downloaded.txt
Listing a big creator takes a while (yt-dlp reads each post's metadata); --save-tsv keeps it for re-runs.
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import reaction_rename as rr  # noqa: E402

CONVENTIONAL_EP = re.compile(r" - S(\d{2})E(\d{2})(?:-E?(\d{2}))?")


def list_posts(url=None, list_file=None, browser="firefox"):
    """[(id, title, url)] via yt-dlp metadata only (no download)."""
    cmd = ["yt-dlp", "--cookies-from-browser", browser, "--simulate", "--ignore-errors", "--no-warnings",
           "--print", "%(id)s\t%(title)s\t%(webpage_url)s"]
    cmd += [url] if url else ["-a", list_file]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    posts = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] not in ("NA", ""):
            posts.append(tuple(parts))
    if not posts:
        sys.exit(f"yt-dlp listed no posts (exit {out.returncode}): {out.stderr.strip()[-400:]}")
    return posts


def episode_info(title):
    """parse() wants a file name; titles have no extension and may contain dots ("Mr. Robot")."""
    info = rr.parse(title + ".mp4")
    if info is None:                                   # already in library style, e.g. "Loki - S01E03"
        m = CONVENTIONAL_EP.search(rr.normalize(title))
        if not m:
            return {"hint": "", "special": True, "note": "unrecognised"}
        hint = rr.normalize(title)[:m.start()].strip()
        return {"hint": hint, "season": int(m[1]), "e1": int(m[2]), "e2": int(m[3]) if m[3] else None, "special": False}
    return info


def classify(posts, root, creator, aliases, show_filter=None):
    idx, _display = rr.library_index(root, aliases)
    rows = []
    for pid, title, url in posts:
        info = episode_info(title)
        if "season" not in info:
            rows.append(("other", info.get("hint", ""), pid, title, url, info.get("note", "")))
            continue
        cands = rr.find_show(info["hint"], idx, aliases, creator)
        show = cands[0][1].name if len(cands) == 1 else (info["hint"] or "?")
        if show_filter and rr.key(show_filter) not in (rr.key(show), rr.key(info["hint"])):
            continue
        if len(cands) != 1:
            rows.append(("new show" if not cands else "ambiguous", show, pid, title, url, ""))
            continue
        wanted = {(info["season"], e) for e in range(info["e1"], (info["e2"] or info["e1"]) + 1)}
        have = rr.episodes_present(cands[0][1])
        ep = f"S{info['season']:02d}E{info['e1']:02d}" + (f"-{info['e2']:02d}" if info["e2"] else "")
        if wanted <= have:
            rows.append(("have", show, pid, title, url, ep))
        elif wanted & have:
            rows.append(("partial", show, pid, title, url, ep + " (has " + ",".join(f"E{e:02d}" for _, e in sorted(wanted & have)) + ")"))
        else:
            rows.append(("missing", show, pid, title, url, ep))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="library root, e.g. \\\\nas\\media\\reaction")
    ap.add_argument("--creator", required=True, help="creator folder in the library (as used by Download-Creator)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="creator page, e.g. https://www.patreon.com/c/<name>/posts")
    src.add_argument("--list-file", help="post URL list (a collection, from Clean-Patreon-PlayList-HTML.ps1)")
    src.add_argument("--from-tsv", help="a listing saved earlier with --save-tsv (no network)")
    ap.add_argument("--save-tsv", help="save the listing (id, title, url) for re-runs")
    ap.add_argument("--show", help="only this show")
    ap.add_argument("--out", default="gaps", help="prefix for the output files (default: gaps)")
    ap.add_argument("--seed-archive", help="append 'patreon <id>' for posts you already have to this yt-dlp archive")
    ap.add_argument("--include-partial", action="store_true", help="also put partly-present posts in the missing list")
    ap.add_argument("--browser", default="firefox")
    ap.add_argument("--aliases", default=None)
    a = ap.parse_args()

    local = Path(rr.__file__).with_name("reaction-aliases.json")
    alias_file = Path(a.aliases) if a.aliases else (local if local.exists() else local.with_suffix(".example.json"))
    aliases = {rr.key(k): v for k, v in json.loads(alias_file.read_text(encoding="utf-8")).items()} if alias_file.exists() else {}

    if a.from_tsv:
        with open(a.from_tsv, encoding="utf-8", newline="") as fh:
            posts = [tuple(r) for r in csv.reader(fh, delimiter="\t") if len(r) == 3]
    else:
        posts = list_posts(a.url, a.list_file, a.browser)
    if a.save_tsv:
        with open(a.save_tsv, "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh, delimiter="\t").writerows(posts)

    rows = classify(posts, a.root, a.creator, aliases, a.show)
    by_show = defaultdict(lambda: defaultdict(list))
    for status, show, pid, title, url, note in rows:
        by_show[show][status].append((note or title))
    print(f"{len(posts)} posts listed for {a.creator}\n")
    for show in sorted(by_show, key=str.lower):
        s = by_show[show]
        counts = ", ".join(f"{k} {len(v)}" for k, v in sorted(s.items()))
        print(f"{show}: {counts}")
        for k in ("missing", "partial", "new show", "ambiguous"):
            if s.get(k):
                print(f"   {k}: " + "; ".join(sorted(s[k])[:12]) + (" …" if len(s[k]) > 12 else ""))

    want = {"missing"} | ({"partial"} if a.include_partial else set())
    missing = [r for r in rows if r[0] in want]
    Path(f"{a.out}-missing.txt").write_text("".join(r[4] + "\n" for r in missing), encoding="utf-8")
    others = [r for r in rows if r[0] in ("other", "new show", "ambiguous")]
    Path(f"{a.out}-review.txt").write_text("".join(f"{r[0]}\t{r[3]}\t{r[4]}\n" for r in others), encoding="utf-8")
    print(f"\n{len(missing)} posts to download -> {a.out}-missing.txt   ({len(others)} to look at -> {a.out}-review.txt)")
    print(f'Next: .\\Download-Creator.ps1 -Creator "{a.creator}" -ListFile {a.out}-missing.txt')

    if a.seed_archive:
        have_ids = [r[2] for r in rows if r[0] == "have"]
        arch = Path(a.seed_archive)
        existing = set(arch.read_text(encoding="utf-8").split("\n")) if arch.exists() else set()
        new = [f"patreon {i}" for i in have_ids if f"patreon {i}" not in existing]
        with open(arch, "a", encoding="utf-8") as fh:
            fh.write("".join(x + "\n" for x in new))
        print(f"seeded {len(new)} already-owned posts into {arch} (future full runs skip them)")


if __name__ == "__main__":
    main()
