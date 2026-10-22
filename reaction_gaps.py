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
Only full reactions count: when a creator marks posts "Full Length" / "Unedited" / "Uncut", their "Edited | ...", "(Cut Reaction)" and short clip
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


TRAILER = re.compile(r"\b(trailer|teaser|opening|ending|recap)\b", re.I)


def alias_terms(alias_file):
    """(regex, show) pairs for show names in titles that have no episode number ("AOT OVA 4" -> Attack on Titan).
    Longest name first; aliases under 3 letters ("IN", "CE") are left out, they hit too much other text."""
    raw = json.loads(alias_file.read_text(encoding="utf-8")) if alias_file.exists() else {}
    names = {**raw, **{v: v for v in raw.values()}}
    names = sorted(((k, v) for k, v in names.items() if len(rr.key(k)) >= 3), key=lambda t: -len(t[0]))
    return [(re.compile(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])", re.I), v) for k, v in names]


def show_for_title(title, terms):
    t = rr.normalize(title)
    return next((v for rx, v in terms if rx.search(t)), None)


PATREON_API = "https://www.patreon.com/api/posts"
COLLECTION_SUFFIX = re.compile(r"\s*\b(reactions?|reacts?)\b\s*$", re.I)


VIDEO_POST_TYPES = {"video_external_file", "video_embed", "video"}   # the rest: text_only, image_file, poll, podcast, livestream ...


def patreon_listing(creator_url, every=10):
    """Every post of a creator from Patreon's public JSON API, with its collection: no login, no yt-dlp.

    Returns (posts, coll_titles): posts = [(id, title, url, post_type)] for ALL posts (also the ones a lower tier
    can't open: titles and collection membership are public), coll_titles = {post id: collection title} (a post in
    several collections keeps the first). The creator page gives the campaign id; then /api/posts?filter[campaign_id]
    with include=collections, 100 per request, following the cursor links (a 3,000-post creator is ~30 requests).
    """
    import urllib.parse
    import urllib.request

    def get(url, as_json=True):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json" if as_json else "text/html"})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8", "replace")
        return json.loads(body) if as_json else body

    html = get(creator_url.rstrip("/").removesuffix("/posts"), as_json=False)
    m = (re.search(r'"campaign":\{"data":\{"id":"(\d+)"', html) or re.search(r'"id":"(\d+)","type":"campaign"', html)
         or re.search(r"/campaigns/(\d+)", html))
    if not m:
        sys.exit(f"no campaign id found on {creator_url} (use the creator's page, e.g. https://www.patreon.com/<name>)")
    q = {"filter[campaign_id]": m[1], "include": "collections", "fields[post]": "title,url,post_type",
         "fields[collection]": "title", "sort": "-published_at", "page[count]": "100", "json-api-version": "1.0"}
    url = PATREON_API + "?" + urllib.parse.urlencode(q)
    titles, coll_of, posts, pages = {}, {}, [], 0
    while url:
        d = get(url)
        pages += 1
        for inc in d.get("included", []):
            if inc.get("type") == "collection":
                titles[inc["id"]] = (inc.get("attributes") or {}).get("title") or ""
        for p in d.get("data", []):
            at = p.get("attributes") or {}
            posts.append((p["id"], rr.normalize(at.get("title") or ""), at.get("url") or f"https://www.patreon.com/posts/{p['id']}",
                          at.get("post_type") or ""))
            ids = [c["id"] for c in ((p.get("relationships") or {}).get("collections") or {}).get("data") or []]
            if ids:
                coll_of[p["id"]] = ids[0]
        url = (d.get("links") or {}).get("next")
        if pages % every == 0:
            print(f"  {pages * 100} posts read ...", file=sys.stderr, flush=True)
    coll_titles = {pid: titles[cid] for pid, cid in coll_of.items() if titles.get(cid)}
    return posts, coll_titles


def patreon_collections(creator_url, cache=None):
    """post id -> collection title (see patreon_listing). `cache` (JSON) is written at the end and lets
    --from-tsv runs stay offline."""
    _posts, result = patreon_listing(creator_url)
    if cache:
        Path(cache).write_text(json.dumps(result, indent=0, ensure_ascii=False), encoding="utf-8")
    print(f"  collections: {len(result)} posts in {len(set(result.values()))} collections"
          + (f" (saved to {cache})" if cache else ""), file=sys.stderr, flush=True)
    return result


NON_SHOW_COLLECTION = re.compile(r"other shows|polls?\b|sketch|song|covers?\b|^movies?$|^misc|^q\s*&\s*a|announcements?", re.I)


def collection_shows(coll_titles, aliases):
    """post id -> show, from collection titles: a trailing 'Reaction' is dropped and the aliases apply
    ('Xmen 97 Reaction' -> X-Men '97, 'Haikyu Reaction' -> Haikyu); a name that is already an alias target keeps
    that spelling ('Attack On Titan' -> Attack on Titan). Grab-bag collections ('All other shows!', polls, sketches,
    song covers, 'Movie Reactions') give no show, so those posts are judged by their titles. Same shape as collection_map()."""
    canon = {rr.key(v): v for v in aliases.values()}
    out = {}
    for pid, title in coll_titles.items():
        name = COLLECTION_SUFFIX.sub("", title).strip()
        if name and not NON_SHOW_COLLECTION.search(name):
            out[pid] = aliases.get(rr.key(name)) or canon.get(rr.key(name)) or rr.pretty(name)
    return out


def collection_map(folder, aliases):
    """post id -> show, from a folder of Patreon collection URL lists: one '<Show>.txt' per collection
    (the Clean-Patreon-PlayList-HTML.ps1 output). The file name is the show, so titles don't have to name it."""
    coll_of = {}
    for f in sorted(Path(folder).glob("*.txt")):
        show = aliases.get(rr.key(f.stem), f.stem)
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.search(r"(\d{6,})", line)
            if m:
                coll_of.setdefault(m[1], show)
    return coll_of


def classify(posts, root, creator, aliases, show_filter=None, terms=(), coll_of=None):
    idx, _display = rr.library_index(root, aliases)
    rows, seen = [], {}
    coll_of = coll_of or {}
    for pid, title, url in posts:
        info = episode_info(title)
        coll = coll_of.get(pid)                            # the collection's show, when the post is in one
        if coll and "season" in info:
            info["hint"] = coll
        if "season" not in info:
            hit = None if TRAILER.search(title) else (coll or show_for_title(title, terms))
            if hit:                                        # a show named without an episode number: "AOT OVA 4", "... with my Girlfriend"
                if show_filter and rr.key(show_filter) != rr.key(hit):
                    continue
                cands = rr.find_show(hit, idx, aliases, creator)
                show = cands[0][1].name if len(cands) == 1 else hit   # report under the folder's name (JJK, not Jujutsu Kaisen)
                rows.append(("missing" if cands else "new show", show, pid, title, url, ""))
                continue
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
    src.add_argument("--patreon", metavar="CREATOR_URL",
                     help="list the creator's video posts from Patreon's public API instead of yt-dlp (seconds, not an "
                          "hour; no login; posts your tier can't open are listed too, the download then skips them), "
                          "collections included: --collections-from is implied")
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
                    help="also count edited / short posts (default: only 'Full Length' / 'Unedited' / 'Uncut' posts when the "
                         "creator marks any that way)")
    ap.add_argument("--browser", default="firefox")
    ap.add_argument("--aliases", default=None)
    ap.add_argument("--collections", default=None,
                    help="folder of collection URL lists, one '<Show>.txt' per Patreon collection: a post in one is "
                         "that show, whatever its title says")
    ap.add_argument("--only-collections", metavar="A,B,...",
                    help="keep only posts in these Patreon collections (names as shown by Patreon, 'Reaction' suffix "
                         "optional, case-insensitive): for a creator where only some shows are wanted")
    ap.add_argument("--collections-from", metavar="CREATOR_URL",
                    help="read every post's collection from Patreon itself (public API, no login; the creator page URL, "
                         "e.g. https://www.patreon.com/<name>): the collection title, minus 'Reaction', is the show. "
                         "Saved to <out>-collections.json and reused by later --from-tsv runs without this option")
    a = ap.parse_args()

    local = Path(rr.__file__).with_name("reaction-aliases.json")
    alias_file = Path(a.aliases) if a.aliases else (local if local.exists() else local.with_suffix(".example.json"))
    aliases = {rr.key(k): v for k, v in json.loads(alias_file.read_text(encoding="utf-8")).items()} if alias_file.exists() else {}

    coll_cache = Path(f"{a.out}-collections.json")
    coll_titles = None
    if a.patreon:
        all_posts, coll_titles = patreon_listing(a.patreon)
        posts = [(i, t, u) for i, t, u, kind in all_posts if kind in VIDEO_POST_TYPES]
        print(f"  {len(all_posts)} posts on Patreon, {len(posts)} with video; {len(coll_titles)} in "
              f"{len(set(coll_titles.values()))} collections", file=sys.stderr, flush=True)
        coll_cache.write_text(json.dumps(coll_titles, indent=0, ensure_ascii=False), encoding="utf-8")
        if a.save_tsv:
            with open(a.save_tsv, "w", encoding="utf-8", newline="") as fh:
                csv.writer(fh, delimiter="\t").writerows(posts)
    elif a.from_tsv:
        posts = read_tsv(a.from_tsv)
    else:
        posts = list_posts(a.url, a.list_file, a.browser, a.save_tsv)   # appends to --save-tsv as it goes

    skipped = []
    if not a.all_versions and any(rr.is_full_length(t) for _, t, _ in posts):
        skipped = [p for p in posts if not rr.is_full_length(p[1])]
        posts = [p for p in posts if rr.is_full_length(p[1])]
    if coll_titles is not None:
        coll_of = collection_shows(coll_titles, aliases)
    elif a.collections_from:
        coll_titles = patreon_collections(a.collections_from, cache=coll_cache)
        coll_of = collection_shows(coll_titles, aliases)
    elif a.collections:
        coll_of = collection_map(a.collections, aliases)
    elif coll_cache.exists():
        coll_titles = json.loads(coll_cache.read_text(encoding="utf-8"))
        coll_of = collection_shows(coll_titles, aliases)
        print(f"  collections from {coll_cache} (re-run with --collections-from to refresh)", file=sys.stderr)
    else:
        coll_of = {}
    if a.only_collections:
        if coll_titles is None:
            sys.exit("--only-collections needs the collections from Patreon (--patreon or --collections-from)")
        wanted = {rr.key(COLLECTION_SUFFIX.sub("", c)) for c in a.only_collections.split(",") if c.strip()}
        keep = {pid for pid, title in coll_titles.items() if rr.key(COLLECTION_SUFFIX.sub("", title)) in wanted}
        before = len(posts)
        posts = [p for p in posts if p[0] in keep]
        print(f"  --only-collections: {len(posts)} of {before} posts are in {', '.join(sorted(wanted))}", file=sys.stderr)
    rows = classify(posts, a.root, a.creator, aliases, a.show, alias_terms(alias_file), coll_of)
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
