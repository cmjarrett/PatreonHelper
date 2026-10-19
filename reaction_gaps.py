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
Movies (no episode number, not a trailer / OVA / special) are compared with <creator>/Movies; --include-movies
puts the missing ones in the download list, --include-new the shows the library doesn't have yet.
Only full reactions count: when a creator marks posts "Full Length" / "Unedited", their "Edited | ..." and short clip
posts ("EPISODE TITLE | SHOW | Reaction 2x11") are skipped (--all-versions includes them).
Listing a big creator takes a while (yt-dlp reads each post's metadata, ~1-2 s per post); progress is printed every
25 posts. With --save-tsv each post is saved as it arrives: an interrupted run resumes where it stopped when started
again with the same --save-tsv, and a later run with --url only reads posts that are new since then.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import reaction_rename as rr  # noqa: E402

CONVENTIONAL_EP = re.compile(r" - S(\d{2})E(\d{2})(?:-E?(\d{2}))?")


def read_tsv(path):
    if not path or not Path(path).exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return [tuple(r) for r in csv.reader(fh, delimiter="\t") if len(r) == 3]


def kill_tree(proc):
    """Stop yt-dlp and its children (on Windows, yt-dlp from pip runs as a python.exe child)."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()


def list_posts(url=None, list_file=None, browser="firefox", save_tsv=None, every=25):
    """[(id, title, url)] via yt-dlp metadata only (no download).

    Streams yt-dlp's output: prints progress every `every` posts and appends each post to `save_tsv` as it
    arrives, so an interrupted or failed listing keeps what it has. With an existing `save_tsv` it resumes:
    posts already in it are skipped by yt-dlp (fed to it as a download archive), and later runs only read new posts.
    """
    posts = read_tsv(save_tsv)
    known = {p[0] for p in posts}
    # --encoding: on Windows, yt-dlp writes a pipe in the console code page ("×" -> byte 0xD7), not UTF-8
    cmd = ["yt-dlp", "--cookies-from-browser", browser, "--simulate", "--ignore-errors", "--no-warnings",
           "--encoding", "utf-8", "--print", "%(id)s\t%(title)s\t%(webpage_url)s"]
    archive = None
    if known:
        archive = Path(f"{save_tsv}.known")
        archive.write_text("".join(f"patreon {i}\n" for i in sorted(known)), encoding="utf-8")
        cmd += ["--download-archive", str(archive)]
        print(f"resuming: {len(known)} posts already in {save_tsv}, reading only the rest", file=sys.stderr, flush=True)
    cmd += [url] if url else ["-a", list_file]
    err_path = Path(f"{save_tsv or 'gaps'}.yt-dlp.log")
    new = 0
    out = open(save_tsv, "a", encoding="utf-8", newline="") if save_tsv else None
    writer = csv.writer(out, delimiter="\t") if out else None
    with open(err_path, "w", encoding="utf-8") as err:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8",
                                errors="replace", bufsize=1, env=env)   # a stray byte never stops the listing
        try:
            for line in proc.stdout:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 3 or parts[0] in ("NA", "") or parts[0] in known:
                    continue
                post = tuple(parts)
                posts.append(post)
                known.add(post[0])
                new += 1
                if writer:
                    writer.writerow(post)
                    out.flush()
                if new % every == 0:
                    print(f"  {new} posts read ...", file=sys.stderr, flush=True)
            proc.wait()
        except KeyboardInterrupt:
            kill_tree(proc)
            print(f"\ninterrupted after {new} new posts" + (f"; they're saved in {save_tsv}: run the same command "
                  "again to resume" if save_tsv else " (use --save-tsv to keep progress)"), file=sys.stderr)
            sys.exit(130)
        finally:
            if out:
                out.close()
            if archive and archive.exists():
                archive.unlink()
    if not posts:
        tail = err_path.read_text(encoding="utf-8", errors="replace").strip()[-400:]
        sys.exit(f"yt-dlp listed no posts (exit {proc.returncode}): {tail}")
    print(f"  listing done: {new} new posts ({len(posts)} total)", file=sys.stderr, flush=True)
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
    rows, seen = [], {}
    for pid, title, url in posts:
        info = episode_info(title)
        if "season" not in info:
            if rr.is_movie(title, info):                   # compared with <creator>/Movies (years ignored)
                if show_filter and rr.key(show_filter) != "movies":
                    continue
                name = rr.movie_title(title + ".mp4")
                have = rr.movie_present(Path(root, creator, "Movies"), name)
                rows.append(("have" if have else "missing", "Movies", pid, title, url, name))
            else:
                rows.append(("other", info.get("hint", ""), pid, title, url, info.get("note", "")))
            continue
        cands = rr.find_show(info["hint"], idx, aliases, creator)
        if len(cands) == 1:
            show = cands[0][1].name
        else:                                              # new show: one name per show key ("x-men '97" = "xmen 97")
            name = aliases.get(rr.key(info["hint"]), info["hint"]) or "?"
            show = seen.setdefault(rr.key(name), rr.pretty(name))
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
    ap.add_argument("--include-new", action="store_true",
                    help="also put shows the library doesn't have yet in the missing list (import them with "
                         "reaction_rename.py --new-shows)")
    ap.add_argument("--include-movies", action="store_true",
                    help="also put movies missing from <creator>/Movies in the missing list")
    ap.add_argument("--all-versions", action="store_true",
                    help="also count edited / short posts (default: only 'Full Length' / 'Unedited' posts when the "
                         "creator marks any that way)")
    ap.add_argument("--browser", default="firefox")
    ap.add_argument("--aliases", default=None)
    a = ap.parse_args()

    local = Path(rr.__file__).with_name("reaction-aliases.json")
    alias_file = Path(a.aliases) if a.aliases else (local if local.exists() else local.with_suffix(".example.json"))
    aliases = {rr.key(k): v for k, v in json.loads(alias_file.read_text(encoding="utf-8")).items()} if alias_file.exists() else {}

    if a.from_tsv:
        posts = read_tsv(a.from_tsv)
    else:
        posts = list_posts(a.url, a.list_file, a.browser, a.save_tsv)   # appends to --save-tsv as it goes

    skipped = []
    if not a.all_versions and any(rr.is_full_length(t) for _, t, _ in posts):
        skipped = [p for p in posts if not rr.is_full_length(p[1])]
        posts = [p for p in posts if rr.is_full_length(p[1])]
    rows = classify(posts, a.root, a.creator, aliases, a.show)
    by_show = defaultdict(lambda: defaultdict(list))
    for status, show, pid, title, url, note in rows:
        by_show[show][status].append((note or title))
    print(f"{len(posts)} full-length posts listed for {a.creator}" if skipped else f"{len(posts)} posts listed for {a.creator}")
    if skipped:
        print(f"   ({len(skipped)} edited / short posts skipped; --all-versions to include them)")
    print()
    for show in sorted(by_show, key=str.lower):
        s = by_show[show]
        counts = ", ".join(f"{k} {len(v)}" for k, v in sorted(s.items()))
        print(f"{show}: {counts}")
        for k in ("missing", "partial", "new show", "ambiguous"):
            if s.get(k):
                print(f"   {k}: " + "; ".join(sorted(s[k])[:12]) + (" …" if len(s[k]) > 12 else ""))

    want = {"missing"} | ({"partial"} if a.include_partial else set()) | ({"new show"} if a.include_new else set())
    missing = [r for r in rows if r[0] in want and (r[1] != "Movies" or a.include_movies)]
    Path(f"{a.out}-missing.txt").write_text("".join(r[4] + "\n" for r in missing), encoding="utf-8")
    others = [r for r in rows if r[0] in ("other", "new show", "ambiguous") and r[0] not in want]
    Path(f"{a.out}-review.txt").write_text("".join(f"{r[0]}\t{r[3]}\t{r[4]}\n" for r in others), encoding="utf-8")
    print(f"\n{len(missing)} posts to download -> {a.out}-missing.txt   ({len(others)} to look at -> {a.out}-review.txt)")
    print(f'Next: .\\Download-Creator.ps1 -Creator "{a.creator}" -ListFile {a.out}-missing.txt')
    if a.include_new or a.include_movies:
        print("      then import with reaction_rename.py --src <downloads> --new-shows (creates new show / Movies folders)")

    if a.seed_archive:
        have_ids = [r[2] for r in rows if r[0] == "have"]
        arch = Path(a.seed_archive)
        arch.parent.mkdir(parents=True, exist_ok=True)       # first run, before Download-Creator created it
        existing = set(arch.read_text(encoding="utf-8").split("\n")) if arch.exists() else set()
        new = [f"patreon {i}" for i in have_ids if f"patreon {i}" not in existing]
        with open(arch, "a", encoding="utf-8") as fh:
            fh.write("".join(x + "\n" for x in new))
        print(f"seeded {len(new)} already-owned posts into {arch} (future full runs skip them)")


if __name__ == "__main__":
    main()
