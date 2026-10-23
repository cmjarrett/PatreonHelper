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
Only full reactions count: when a creator marks posts "Full Length" / "Unedited" / "Uncut", their "Edited | ...",
"(Cut Reaction)" and short clip posts ("EPISODE TITLE | SHOW | Reaction 2x11") are skipped (--all-versions includes them).
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


# ======================================================================================================
# Patterns and constants
# ======================================================================================================

# a title already in library style: "Loki - S01E03" or "Loki - S01E03-04"
CONVENTIONAL_EP = re.compile(r" - S(\d{2})E(\d{2})(?:-E?(\d{2}))?")

# no episode number, but clearly not a movie
TRAILER = re.compile(r"\b(trailer|teaser|opening|ending|recap)\b", re.I)
MOVIE_WORD = re.compile(r"\b(movie|film)\b|\(\d{4}\)", re.I)
# an episode the parser couldn't place ("Band Of Brothers E1 - Currahee", "The Pacific - Part 5", "HxH ep 27"):
# not a movie, whatever its collection looks like
EPISODE_LIKE = re.compile(r"\b(?:e|ep|eps|episode|part|pt|chapter)\.?\s*\d{1,3}\b", re.I)

PATREON_API = "https://www.patreon.com/api/posts"

# Where the campaign id sits on a creator's page, most specific first (the first pattern that matches wins)
CAMPAIGN_ID_PATTERNS = (
    r'"campaign":\{"data":\{"id":"(\d+)"',
    r'"id":"(\d+)","type":"campaign"',
    r"/campaigns/(\d+)",
)

# Trailing markers on collection names that aren't part of the show: "Haikyu Reaction", "Black Mirror Collection",
# "Attack on Titan | Watch Along", "Game Of Thrones (Early Access)", "Better Call Saul -Early Access", "Knight o/t 7
# Kingdoms | EA", "SQUID GAME (Full Length)", "The Last Dance - All Episodes". Stripped repeatedly ("Movie Reactions | Watch Alongs").
COLLECTION_MARKERS = re.compile(
    r"\s*(?:[|│\-–:]\s*)?[(\[]?\s*(?:reactions?|reacts?|collection|series|watch[\s-]*alongs?|early(?:[\s-]*acces?s)?|"
    r"full[\s-]*length|all episodes|ea|wa)\s*[)\]]?\s*!*\s*$", re.I)
COLLECTION_SUFFIX = COLLECTION_MARKERS   # kept for callers; prefer collection_name()

# Collections that aren't a show: grab bags, and movie collections ("Movie Vault", "Marvel Movie", "DC Movies"): their
# posts are judged by their titles instead (movies go to <creator>/Movies, like the renamer files them).
NON_SHOW_COLLECTION = re.compile(
    r"other shows|polls?\b|sketch|song|covers?\b|\bmovies?\b|\bfilms?\b|^misc|^q\s*&\s*a|announcements?|live\s*streams?|"
    r"vlogs?\b|bloopers?|blocked|megafan|requests?\b|playthrough|play\s*/\s*watch|lego|trailers?\b|halloween|specials?$", re.I)

VIDEO_POST_TYPES = {"video_external_file", "video_embed", "video"}   # the rest: text_only, image_file, poll, podcast, livestream ...


# ======================================================================================================
# Listing a creator's posts: yt-dlp (titles only) or Patreon's public API
# ======================================================================================================

def read_tsv(path):
    """A saved listing: [(id, title, url)]. A missing file is an empty listing; malformed lines are dropped."""
    if not path or not Path(path).exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return [tuple(row) for row in csv.reader(fh, delimiter="\t") if len(row) == 3]


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
    # ---- 1. what an earlier, interrupted run already saved ----
    posts = read_tsv(save_tsv)
    known_ids = {post[0] for post in posts}

    # ---- 2. the yt-dlp command ----
    # --encoding: on Windows, yt-dlp writes a pipe in the console code page ("×" -> byte 0xD7), not UTF-8
    cmd = ["yt-dlp", "--cookies-from-browser", browser, "--simulate", "--ignore-errors", "--no-warnings",
           "--encoding", "utf-8", "--print", "%(id)s\t%(title)s\t%(webpage_url)s"]

    # Resume: hand the known ids to yt-dlp as a download archive so it doesn't re-read those posts
    archive = None
    if known_ids:
        archive = Path(f"{save_tsv}.known")
        archive.write_text("".join(f"patreon {post_id}\n" for post_id in sorted(known_ids)), encoding="utf-8")
        cmd += ["--download-archive", str(archive)]
        print(f"resuming: {len(known_ids)} posts already in {save_tsv}, reading only the rest", file=sys.stderr, flush=True)

    cmd += [url] if url else ["-a", list_file]

    # ---- 3. stream the output, saving each new post as it arrives ----
    log_path = Path(f"{save_tsv or 'gaps'}.yt-dlp.log")
    new_count = 0
    tsv_handle = open(save_tsv, "a", encoding="utf-8", newline="") if save_tsv else None
    tsv_writer = csv.writer(tsv_handle, delimiter="\t") if tsv_handle else None

    with open(log_path, "w", encoding="utf-8") as log_handle:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log_handle, text=True, encoding="utf-8",
                                errors="replace", bufsize=1, env=env)   # a stray byte never stops the listing
        try:
            for line in proc.stdout:
                fields = line.rstrip("\n").split("\t")

                # not an "id<TAB>title<TAB>url" line, or yt-dlp had no id ("NA"), or we already have the post
                if len(fields) != 3:
                    continue
                post_id = fields[0]
                if post_id in ("NA", "") or post_id in known_ids:
                    continue

                post = tuple(fields)
                posts.append(post)
                known_ids.add(post_id)
                new_count += 1

                if tsv_writer:
                    tsv_writer.writerow(post)
                    tsv_handle.flush()           # saved now, so an interrupt loses nothing

                if new_count % every == 0:
                    print(f"  {new_count} posts read ...", file=sys.stderr, flush=True)
            proc.wait()

        except KeyboardInterrupt:
            kill_tree(proc)
            if save_tsv:
                saved_note = f"; they're saved in {save_tsv}: run the same command again to resume"
            else:
                saved_note = " (use --save-tsv to keep progress)"
            print(f"\ninterrupted after {new_count} new posts{saved_note}", file=sys.stderr)
            sys.exit(130)

        finally:
            if tsv_handle:
                tsv_handle.close()
            if archive and archive.exists():
                archive.unlink()

    # ---- 4. nothing listed at all: show the tail of yt-dlp's log ----
    if not posts:
        log_tail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-400:]
        sys.exit(f"yt-dlp listed no posts (exit {proc.returncode}): {log_tail}")

    print(f"  listing done: {new_count} new posts ({len(posts)} total)", file=sys.stderr, flush=True)
    return posts


def patreon_listing(creator_url, every=10):
    """Every post of a creator from Patreon's public JSON API, with its collection: no login, no yt-dlp.

    Returns (posts, coll_titles): posts = [(id, title, url, post_type)] for ALL posts (also the ones a lower tier
    can't open: titles and collection membership are public), coll_titles = {post id: collection title} (a post in
    several collections keeps the first). The creator page gives the campaign id; then /api/posts?filter[campaign_id]
    with include=collections, 100 per request, following the cursor links (a 3,000-post creator is ~30 requests).
    """
    import time
    import urllib.parse
    import urllib.request

    def get(url, as_json=True):
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json" if as_json else "text/html"})

        for attempt in range(4):                           # Patreon resets the connection now and then: wait and retry
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = response.read().decode("utf-8", "replace")
                return json.loads(body) if as_json else body

            except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
                is_last_attempt = attempt == 3
                if is_last_attempt:
                    raise
                wait_seconds = 5 * 3 ** attempt            # 5 s, 15 s, 45 s
                print(f"  Patreon: {getattr(error, 'reason', error)}; retrying in {wait_seconds} s", file=sys.stderr, flush=True)
                time.sleep(wait_seconds)

    # ---- 1. the creator page gives the campaign id ----
    creator_page_url = creator_url.rstrip("/").removesuffix("/posts")
    html = get(creator_page_url, as_json=False)

    campaign_match = None
    for pattern in CAMPAIGN_ID_PATTERNS:
        campaign_match = re.search(pattern, html)
        if campaign_match:
            break
    if not campaign_match:
        sys.exit(f"no campaign id found on {creator_url} (use the creator's page, e.g. https://www.patreon.com/<name>)")

    # ---- 2. the first page of the posts API, collections included ----
    query = {"filter[campaign_id]": campaign_match[1], "include": "collections", "fields[post]": "title,url,post_type",
             "fields[collection]": "title", "sort": "-published_at", "page[count]": "100", "json-api-version": "1.0"}
    page_url = PATREON_API + "?" + urllib.parse.urlencode(query)

    collection_titles = {}      # collection id -> title
    collection_of_post = {}     # post id -> collection id (the first one, when a post is in several)
    posts = []
    pages_read = 0

    # ---- 3. follow the cursor links until there is no next page ----
    while page_url:
        page = get(page_url)
        pages_read += 1

        for included in page.get("included", []):
            if included.get("type") == "collection":
                collection_titles[included["id"]] = (included.get("attributes") or {}).get("title") or ""

        for post in page.get("data", []):
            attributes = post.get("attributes") or {}
            title = rr.normalize(attributes.get("title") or "")
            post_url = attributes.get("url") or f"https://www.patreon.com/posts/{post['id']}"
            post_type = attributes.get("post_type") or ""
            posts.append((post["id"], title, post_url, post_type))

            relationships = post.get("relationships") or {}
            collection_refs = (relationships.get("collections") or {}).get("data") or []
            collection_ids = [ref["id"] for ref in collection_refs]
            if collection_ids:
                collection_of_post[post["id"]] = collection_ids[0]

        page_url = (page.get("links") or {}).get("next")
        if pages_read % every == 0:
            print(f"  {pages_read * 100} posts read ...", file=sys.stderr, flush=True)

    # ---- 4. post id -> collection title, only for collections that have a title ----
    coll_titles = {post_id: collection_titles[collection_id]
                   for post_id, collection_id in collection_of_post.items()
                   if collection_titles.get(collection_id)}
    return posts, coll_titles


def patreon_collections(creator_url, cache=None):
    """post id -> collection title (see patreon_listing). `cache` (JSON) is written at the end and lets
    --from-tsv runs stay offline."""
    _posts, result = patreon_listing(creator_url)
    if cache:
        Path(cache).write_text(json.dumps(result, indent=0, ensure_ascii=False), encoding="utf-8")

    saved_note = f" (saved to {cache})" if cache else ""
    print(f"  collections: {len(result)} posts in {len(set(result.values()))} collections{saved_note}",
          file=sys.stderr, flush=True)
    return result


# ======================================================================================================
# Reading titles: episode, show, collection, version
# ======================================================================================================

def episode_info(title):
    """parse() wants a file name; titles have no extension and may contain dots ("Mr. Robot")."""
    info = rr.parse(title + ".mp4")
    if info is not None:
        return info

    # parse() returns None for a title already in library style, e.g. "Loki - S01E03"
    normalized = rr.normalize(title)
    match = CONVENTIONAL_EP.search(normalized)
    if not match:
        return {"hint": "", "special": True, "note": "unrecognised"}

    show_hint = normalized[:match.start()].strip()
    season = int(match[1])
    first_episode = int(match[2])
    last_episode = int(match[3]) if match[3] else None
    return {"hint": show_hint, "season": season, "e1": first_episode, "e2": last_episode, "special": False}


def alias_terms(alias_file):
    """(regex, show) pairs for show names in titles that have no episode number ("AOT OVA 4" -> Attack on Titan).
    Longest name first; aliases under 3 letters ("IN", "CE") are left out, they hit too much other text."""
    raw = json.loads(alias_file.read_text(encoding="utf-8")) if alias_file.exists() else {}

    # the show's own name counts as well as its aliases
    names = {**raw, **{show: show for show in raw.values()}}
    long_enough = [(name, show) for name, show in names.items() if len(rr.key(name)) >= 3]
    longest_first = sorted(long_enough, key=lambda pair: -len(pair[0]))

    # whole words only: not glued to a letter or digit on either side
    terms = []
    for name, show in longest_first:
        whole_word = re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", re.I)
        terms.append((whole_word, show))
    return terms


def show_for_title(title, terms):
    """The first alias term found in the title (see alias_terms), else None."""
    normalized = rr.normalize(title)
    return next((show for regex, show in terms if regex.search(normalized)), None)


def collection_name(title):
    """The show part of a Patreon collection title (markers stripped, see COLLECTION_MARKERS)."""
    name = title.strip()
    while True:
        stripped = COLLECTION_MARKERS.sub("", name).strip(" -–|│:!")
        if stripped == name:
            return name
        name = stripped


def collection_shows(coll_titles, aliases):
    """post id -> show, from collection titles: a trailing 'Reaction' is dropped and the aliases apply
    ('Xmen 97 Reaction' -> X-Men '97, 'Haikyu Reaction' -> Haikyu); a name that is already an alias target keeps
    that spelling ('Attack On Titan' -> Attack on Titan). Grab-bag collections ('All other shows!', polls, sketches,
    song covers, 'Movie Reactions') give no show, so those posts are judged by their titles. Same shape as collection_map()."""
    canonical_names = {rr.key(show): show for show in aliases.values()}
    show_of_post = {}

    for post_id, title in coll_titles.items():
        name = collection_name(title)
        if not name or NON_SHOW_COLLECTION.search(name):
            continue

        if name.isupper():                             # "THE BEAR", "SQUID GAME": a folder name, not a shout
            name = name.title()
        name_key = rr.key(name)
        show_of_post[post_id] = aliases.get(name_key) or canonical_names.get(name_key) or rr.pretty(name)

    return show_of_post


def post_version(title, coll_title, full_rx=None, cut_rx=None):
    """'full' | 'cut' | None: the post's own marker ("Full Length", "Uncut" / "Edited |", "(Cut Reaction)"), else the
    marker in its collection's name ("Severance (Full Length)", "Game Of Thrones (Early Access)"). `full_rx` /
    `cut_rx` add a creator's own words (--full-marker / --cut-marker: "watch along", "early access")."""
    # the post's own title is checked first and wins over its collection's name
    for text in (title, coll_title or ""):
        normalized = rr.normalize(text)

        starts_with_edited = re.match(r"\s*edited\b", normalized, re.I)
        has_cut_marker = rr.CUT_VERSION.search(normalized) or (cut_rx and cut_rx.search(normalized))
        if starts_with_edited or has_cut_marker:
            return "cut"

        # (within one text, a cut marker wins over a full marker: it is checked first)
        has_full_marker = rr.FULL_LENGTH.search(normalized) or (full_rx and full_rx.search(normalized))
        if has_full_marker:
            return "full"
    return None


def collection_map(folder, aliases):
    """post id -> show, from a folder of Patreon collection URL lists: one '<Show>.txt' per collection
    (the Clean-Patreon-PlayList-HTML.ps1 output). The file name is the show, so titles don't have to name it."""
    show_of_post = {}
    for list_file in sorted(Path(folder).glob("*.txt")):
        show = aliases.get(rr.key(list_file.stem), list_file.stem)
        for line in list_file.read_text(encoding="utf-8").splitlines():
            id_match = re.search(r"(\d{6,})", line)
            if id_match:
                show_of_post.setdefault(id_match[1], show)   # a post in several lists keeps the first
    return show_of_post


# ======================================================================================================
# Comparing posts with the library
# ======================================================================================================

def looks_like_movie(title, info, coll, movie_collection):
    """A post with no episode number that is a movie. A movie in a franchise collection is still a movie
    ("John Wick 2", "Logan"); but inside a show's collection a bare number ("HxH 100", "DS 21") is an episode the
    parser couldn't place, not a movie, unless the title says movie/film or carries a year."""
    if not rr.is_movie(title, info):
        return False
    if not coll:                                           # in no collection: the title alone decides
        return True
    if MOVIE_WORD.search(title):
        return True
    if EPISODE_LIKE.search(title):
        return False
    if coll in movie_collection:
        return True

    title_ends_in_number = re.search(r"\d\s*$", rr.normalize(title).rstrip(" !.)"))
    return not title_ends_in_number


def classify(posts, root, creator, aliases, show_filter=None, terms=(), coll_of=None):
    """One row per post: (status, show, post id, title, url, note).
    status: have | missing | partial | new show | ambiguous | other."""
    library_idx, _display = rr.library_index(root, aliases)
    rows = []
    new_show_names = {}                                    # show key -> the one spelling used for a show not in the library
    coll_of = coll_of or {}
    infos = {pid: episode_info(title) for pid, title, _ in posts}

    # ---- 1. which collections are movie franchises ----
    # share of posts with an episode number per collection: a franchise collection of movies ("John Wick",
    # "X-Men", "The Lord of the Rings") has none, a show's collection has most
    posts_in_collection = defaultdict(int)
    episodes_in_collection = defaultdict(int)
    for pid, _, _ in posts:
        if pid in coll_of:
            posts_in_collection[coll_of[pid]] += 1
            episodes_in_collection[coll_of[pid]] += "season" in infos[pid]
    movie_collection = {c for c in posts_in_collection
                        if posts_in_collection[c] >= 2 and episodes_in_collection[c] / posts_in_collection[c] < 0.25}

    # ---- 2. judge each post ----
    for pid, title, url in posts:
        info = infos[pid]
        coll = coll_of.get(pid)                            # the collection's show, when the post is in one

        # -- 2a. an episode in a collection: the collection can override the title's show --
        if coll and "season" in info:
            # the title's own show wins when it names an existing folder of this creator: a "Marvel Cinematic
            # Universe" collection holds Daredevil episodes, and those belong in Daredevil
            title_hint = info.get("hint", "")
            own_matches = rr.find_show(title_hint, library_idx, aliases, creator) if title_hint else []
            if len(own_matches) != 1:
                info["hint"] = coll

        # -- 2b. no episode number: a movie, a show without numbers, or something else --
        if "season" not in info:
            is_movie = looks_like_movie(title, info, coll, movie_collection)
            if is_movie or TRAILER.search(title):
                named_show = None
            else:
                named_show = coll or show_for_title(title, terms)

            if named_show:                                 # a show named without an episode number: "AOT OVA 4", "... with my Girlfriend"
                if show_filter and rr.key(show_filter) != rr.key(named_show):
                    continue
                candidates = rr.find_show(named_show, library_idx, aliases, creator)
                # report under the folder's name (JJK, not Jujutsu Kaisen)
                show = candidates[0][1].name if len(candidates) == 1 else named_show
                status = "missing" if candidates else "new show"
                rows.append((status, show, pid, title, url, ""))
                continue

            if is_movie:                                   # compared with <creator>/Movies (years ignored)
                if show_filter and rr.key(show_filter) != "movies":
                    continue
                movie_name = rr.movie_title(title + ".mp4")
                already_there = rr.movie_present(Path(root, creator, "Movies"), movie_name)
                rows.append(("have" if already_there else "missing", "Movies", pid, title, url, movie_name))
            else:
                rows.append(("other", info.get("hint", ""), pid, title, url, info.get("note", "")))
            continue

        # -- 2c. an episode: find its show folder --
        candidates = rr.find_show(info["hint"], library_idx, aliases, creator)
        if len(candidates) == 1:
            show = candidates[0][1].name
        else:                                              # new show: one name per show key ("x-men '97" = "xmen 97")
            name = aliases.get(rr.key(info["hint"]), info["hint"]) or "?"
            show = new_show_names.setdefault(rr.key(name), rr.pretty(name))

        if show_filter and rr.key(show_filter) not in (rr.key(show), rr.key(info["hint"])):
            continue

        if len(candidates) != 1:                           # no folder at all, or the show exists under two creators
            status = "new show" if not candidates else "ambiguous"
            rows.append((status, show, pid, title, url, ""))
            continue

        # -- 2d. an episode in a known show: which of its episodes does the library have? --
        last_episode = info["e2"] or info["e1"]
        wanted = {(info["season"], e) for e in range(info["e1"], last_episode + 1)}
        have = rr.episodes_present(candidates[0][1])

        episode_label = f"S{info['season']:02d}E{info['e1']:02d}"
        if info["e2"]:
            episode_label += f"-{info['e2']:02d}"

        if wanted <= have:
            rows.append(("have", show, pid, title, url, episode_label))
        elif wanted & have:
            have_list = ",".join(f"E{e:02d}" for _, e in sorted(wanted & have))
            rows.append(("partial", show, pid, title, url, f"{episode_label} (has {have_list})"))
        else:
            rows.append(("missing", show, pid, title, url, episode_label))

    return rows


# ======================================================================================================
# Command line
# ======================================================================================================

def main():
    # ---- 1. arguments ----
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="library root, e.g. \\\\nas\\media\\reaction")
    parser.add_argument("--creator", required=True, help="creator folder in the library (as used by Download-Creator)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="creator page, e.g. https://www.patreon.com/c/<name>/posts")
    src.add_argument("--list-file", help="post URL list (a collection, from Clean-Patreon-PlayList-HTML.ps1)")
    src.add_argument("--from-tsv", help="a listing saved earlier with --save-tsv (no network)")
    src.add_argument("--patreon", metavar="CREATOR_URL",
                     help="list the creator's video posts from Patreon's public API instead of yt-dlp (seconds, not an "
                          "hour; no login; posts your tier can't open are listed too, the download then skips them), "
                          "collections included: --collections-from is implied")
    parser.add_argument("--save-tsv", help="save the listing (id, title, url) for re-runs")
    parser.add_argument("--show", help="only this show")
    parser.add_argument("--out", default="gaps", help="prefix for the output files (default: gaps)")
    parser.add_argument("--seed-archive", help="append 'patreon <id>' for posts you already have to this yt-dlp archive")
    parser.add_argument("--include-partial", action="store_true", help="also put partly-present posts in the missing list")
    parser.add_argument("--include-new", action="store_true",
                        help="also put shows the library doesn't have yet in the missing list (import them with "
                             "reaction_rename.py --new-shows)")
    parser.add_argument("--include-movies", action="store_true",
                        help="also put movies missing from <creator>/Movies in the missing list")
    parser.add_argument("--all-versions", action="store_true",
                        help="also count edited / short posts (default: only 'Full Length' / 'Unedited' / 'Uncut' posts when the "
                             "creator marks any that way)")
    parser.add_argument("--browser", default="firefox")
    parser.add_argument("--aliases", default=None)
    parser.add_argument("--collections", default=None,
                        help="folder of collection URL lists, one '<Show>.txt' per Patreon collection: a post in one is "
                             "that show, whatever its title says")
    parser.add_argument("--full-marker", metavar="REGEX", help="a creator's own word for the full reaction, in titles or "
                        "collection names (e.g. 'watch along'); 'Full Length' / 'Unedited' / 'Uncut' always count")
    parser.add_argument("--cut-marker", metavar="REGEX", help="a creator's own word for the edited one (e.g. 'early access'); "
                        "'Edited |' and '(Cut Reaction)' always count")
    parser.add_argument("--unmarked", choices=["edited", "full"], default="edited",
                        help="what an unmarked post is when the creator marks some posts full-length (default: edited, so "
                             "it's skipped; 'full' for creators that mark the edited ones instead)")
    parser.add_argument("--only-collections", metavar="A,B,...",
                        help="keep only posts in these Patreon collections (names as shown by Patreon, 'Reaction' suffix "
                             "optional, case-insensitive): for a creator where only some shows are wanted")
    parser.add_argument("--collections-from", metavar="CREATOR_URL",
                        help="read every post's collection from Patreon itself (public API, no login; the creator page URL, "
                             "e.g. https://www.patreon.com/<name>): the collection title, minus 'Reaction', is the show. "
                             "Saved to <out>-collections.json and reused by later --from-tsv runs without this option")
    args = parser.parse_args()

    # ---- 2. show-name aliases: your own reaction-aliases.json, else the example file ----
    local_aliases = Path(rr.__file__).with_name("reaction-aliases.json")
    if args.aliases:
        alias_file = Path(args.aliases)
    elif local_aliases.exists():
        alias_file = local_aliases
    else:
        alias_file = local_aliases.with_suffix(".example.json")

    if alias_file.exists():
        raw_aliases = json.loads(alias_file.read_text(encoding="utf-8"))
        aliases = {rr.key(name): show for name, show in raw_aliases.items()}
    else:
        aliases = {}

    # ---- 3. the posts: Patreon's API, a saved listing, or a yt-dlp listing ----
    coll_cache = Path(f"{args.out}-collections.json")
    coll_titles = None                                     # post id -> collection title, when known
    if args.patreon:
        all_posts, coll_titles = patreon_listing(args.patreon)
        posts = [(post_id, title, url) for post_id, title, url, post_type in all_posts if post_type in VIDEO_POST_TYPES]
        print(f"  {len(all_posts)} posts on Patreon, {len(posts)} with video; {len(coll_titles)} in "
              f"{len(set(coll_titles.values()))} collections", file=sys.stderr, flush=True)
        coll_cache.write_text(json.dumps(coll_titles, indent=0, ensure_ascii=False), encoding="utf-8")
        if args.save_tsv:
            with open(args.save_tsv, "w", encoding="utf-8", newline="") as fh:
                csv.writer(fh, delimiter="\t").writerows(posts)
    elif args.from_tsv:
        posts = read_tsv(args.from_tsv)
    else:
        posts = list_posts(args.url, args.list_file, args.browser, args.save_tsv)   # appends to --save-tsv as it goes

    # ---- 4. which show each post belongs to, when its collection says ----
    if coll_titles is not None:                            # --patreon just read them
        coll_of = collection_shows(coll_titles, aliases)
    elif args.collections_from:
        coll_titles = patreon_collections(args.collections_from, cache=coll_cache)
        coll_of = collection_shows(coll_titles, aliases)
    elif args.collections:
        coll_of = collection_map(args.collections, aliases)
    elif coll_cache.exists():                              # saved by an earlier --patreon / --collections-from run
        coll_titles = json.loads(coll_cache.read_text(encoding="utf-8"))
        coll_of = collection_shows(coll_titles, aliases)
        print(f"  collections from {coll_cache} (re-run with --collections-from to refresh)", file=sys.stderr)
    else:
        coll_of = {}

    # ---- 5. --only-collections: keep just the posts in the named collections ----
    if args.only_collections:
        if coll_titles is None:
            sys.exit("--only-collections needs the collections from Patreon (--patreon or --collections-from)")
        wanted_collections = {rr.key(collection_name(name)) for name in args.only_collections.split(",") if name.strip()}
        ids_in_wanted_collections = {post_id for post_id, title in coll_titles.items()
                                     if rr.key(collection_name(title)) in wanted_collections}
        posts_before = len(posts)
        posts = [post for post in posts if post[0] in ids_in_wanted_collections]
        print(f"  --only-collections: {len(posts)} of {posts_before} posts are in {', '.join(sorted(wanted_collections))}",
              file=sys.stderr)

    # ---- 6. full-length only: drop the edited / short versions ----
    # a post's own marker, else its collection's; unmarked posts are edited (Emme, Haylo & Kiss:
    # the full ones say so) unless --unmarked full (Diegesis: "Early Access" = edited, the rest is full)
    skipped = []
    full_rx = re.compile(args.full_marker, re.I) if args.full_marker else None
    cut_rx = re.compile(args.cut_marker, re.I) if args.cut_marker else None
    version = {post_id: post_version(title, (coll_titles or {}).get(post_id), full_rx, cut_rx)
               for post_id, title, _ in posts}

    creator_marks_full_posts = any(v == "full" for v in version.values())
    if not args.all_versions and creator_marks_full_posts:
        kept_versions = {"full"} | ({None} if args.unmarked == "full" else set())
        skipped = [post for post in posts if version[post[0]] not in kept_versions]
        posts = [post for post in posts if version[post[0]] in kept_versions]

    # ---- 7. compare with the library and print the report ----
    rows = classify(posts, args.root, args.creator, aliases, args.show, alias_terms(alias_file), coll_of)

    by_show = defaultdict(lambda: defaultdict(list))       # show -> status -> [note or title]
    for status, show, pid, title, url, note in rows:
        by_show[show][status].append(note or title)

    if skipped:
        print(f"{len(posts)} full-length posts listed for {args.creator}")
        print(f"   ({len(skipped)} edited / short posts skipped; --all-versions to include them)")
    else:
        print(f"{len(posts)} posts listed for {args.creator}")
    print()

    for show in sorted(by_show, key=str.lower):
        by_status = by_show[show]
        counts = ", ".join(f"{status} {len(items)}" for status, items in sorted(by_status.items()))
        print(f"{show}: {counts}")

        for status in ("missing", "partial", "new show", "ambiguous"):
            items = by_status.get(status)
            if items:
                more = " …" if len(items) > 12 else ""      # the first 12 only
                print(f"   {status}: " + "; ".join(sorted(items)[:12]) + more)

    # ---- 8. write the download list and the review list ----
    wanted_statuses = {"missing"}
    if args.include_partial:
        wanted_statuses.add("partial")
    if args.include_new:
        wanted_statuses.add("new show")

    # movies are only downloaded on request (--include-movies)
    to_download = [row for row in rows
                   if row[0] in wanted_statuses and (row[1] != "Movies" or args.include_movies)]
    Path(f"{args.out}-missing.txt").write_text("".join(row[4] + "\n" for row in to_download), encoding="utf-8")

    # what's left for a human to look at: not an episode, a new show, or a show found under two creators
    to_review = [row for row in rows
                 if row[0] in ("other", "new show", "ambiguous") and row[0] not in wanted_statuses]
    Path(f"{args.out}-review.txt").write_text("".join(f"{row[0]}\t{row[3]}\t{row[4]}\n" for row in to_review),
                                              encoding="utf-8")

    print(f"\n{len(to_download)} posts to download -> {args.out}-missing.txt   ({len(to_review)} to look at -> {args.out}-review.txt)")
    print(f'Next: .\\Download-Creator.ps1 -Creator "{args.creator}" -ListFile {args.out}-missing.txt')
    if args.include_new or args.include_movies:
        print("      then import with reaction_rename.py --src <downloads> --new-shows (creates new show / Movies folders)")

    # ---- 9. --seed-archive: tell yt-dlp about the posts already owned ----
    if args.seed_archive:
        owned_ids = [row[2] for row in rows if row[0] == "have"]
        archive_path = Path(args.seed_archive)
        archive_path.parent.mkdir(parents=True, exist_ok=True)       # first run, before Download-Creator created it

        existing_lines = set(archive_path.read_text(encoding="utf-8").split("\n")) if archive_path.exists() else set()
        new_lines = [f"patreon {post_id}" for post_id in owned_ids if f"patreon {post_id}" not in existing_lines]
        with open(archive_path, "a", encoding="utf-8") as fh:
            fh.write("".join(line + "\n" for line in new_lines))
        print(f"seeded {len(new_lines)} already-owned posts into {archive_path} (future full runs skip them)")


if __name__ == "__main__":
    main()
