"""Tests for reaction_gaps.py: fake library + a saved post listing (no network, no yt-dlp).
    python test_reaction_gaps.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"\n     got  {got!r}\n     want {want!r}")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp, "reaction")
    lib = {
        "Creator A/Vinland Saga": ["Vinland Saga - S01E01.mp4", "Vinland Saga - S01E02.mp4", "Vinland Saga - S01E03.mp4"],
        "Creator A/Demon Slayer": [f"Demon Slayer - S02E{e:02d}.mp4" for e in range(8, 12)],
        "Creator B/Loki": ["Loki - S01E01.mkv"],
    }
    for d, files in lib.items():
        Path(root, d).mkdir(parents=True)
        for f in files:
            Path(root, d, f).write_bytes(b"x")
    tsv = Path(tmp, "posts.tsv")
    posts = [
        ("101", "Full Length ｜ Vinland Saga ｜ 1x2", "https://www.patreon.com/posts/101"),           # have
        ("102", "Full Length ｜ Vinland Saga ｜ 1x4", "https://www.patreon.com/posts/102"),           # missing
        ("103", "Full Length ｜ Vinland Saga ｜ 2x1", "https://www.patreon.com/posts/103"),           # missing (new season)
        ("104", "Demon Slayer ｜ S2 x E8-11 ｜ Unedited Reaction", "https://www.patreon.com/posts/104"),  # have (as singles)
        ("105", "Demon Slayer ｜ S2 x E10-13 ｜ Unedited Reaction", "https://www.patreon.com/posts/105"), # partial
        ("106", "Mr. Robot ｜ 1x01", "https://www.patreon.com/posts/106"),                            # new show (dot in name)
        ("107", "Infinity Castle ｜ Trailer Reaction", "https://www.patreon.com/posts/107"),          # other
        ("108", "Vinland Saga - S01E03", "https://www.patreon.com/posts/108"),                       # conventional title, have
    ]
    tsv.write_text("".join("\t".join(p) + "\n" for p in posts), encoding="utf-8")
    arch = Path(tmp, "downloaded.txt")
    arch.write_text("patreon 104\n", encoding="utf-8")
    out = Path(tmp, "gaps")
    r = subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                        "--from-tsv", str(tsv), "--out", str(out), "--seed-archive", str(arch), "--all-versions"],
                       capture_output=True, text=True, encoding="utf-8")
    print(r.stdout if fails else "", r.stderr[-800:])
    missing = Path(f"{out}-missing.txt").read_text(encoding="utf-8").split()
    check("missing list = the two absent Vinland posts", sorted(missing),
          ["https://www.patreon.com/posts/102", "https://www.patreon.com/posts/103"])
    check("partial not in missing by default", "https://www.patreon.com/posts/105" in missing, False)
    review = Path(f"{out}-review.txt").read_text(encoding="utf-8")
    check("new show (title with a dot) -> review", "new show\tMr. Robot" in review, True)
    check("trailer -> review", "Infinity Castle" in review, True)
    check("report shows Vinland counts", "Vinland Saga: have 2, missing 2" in r.stdout, True)
    check("report shows the partial", "partial: S02E10-13 (has E10,E11)" in r.stdout, True)
    a = arch.read_text(encoding="utf-8").split("\n")
    check("archive seeded with owned posts, no duplicates", sorted(x for x in a if x),
          ["patreon 101", "patreon 104", "patreon 108"])
    r2 = subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                         "--from-tsv", str(tsv), "--out", str(out), "--include-partial", "--show", "Demon Slayer"],
                        capture_output=True, text=True, encoding="utf-8")
    m2 = Path(f"{out}-missing.txt").read_text(encoding="utf-8").split()
    check("--show + --include-partial", m2, ["https://www.patreon.com/posts/105"])
    subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                    "--from-tsv", str(tsv), "--out", str(out), "--all-versions", "--include-new"],
                   capture_output=True, text=True, encoding="utf-8")
    check("--include-new adds the new show", "https://www.patreon.com/posts/106" in
          Path(f"{out}-missing.txt").read_text(encoding="utf-8").split(), True)
    # movies: compared with <creator>/Movies; only --include-movies puts the missing ones in the list
    Path(root, "Creator A", "Movies").mkdir()
    Path(root, "Creator A", "Movies", "Interstellar (2014).mp4").write_bytes(b"x")
    tsv3 = Path(tmp, "movies.tsv")
    tsv3.write_text("".join("\t".join(p) + "\n" for p in [
        ("301", "Interstellar ｜ Unedited Reaction", "https://www.patreon.com/posts/301"),
        ("302", "Jaws ｜ Unedited Reaction", "https://www.patreon.com/posts/302"),
        ("303", "Infinity Castle ｜ Trailer ｜ Unedited Reaction", "https://www.patreon.com/posts/303"),
    ]), encoding="utf-8")
    r5 = subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                         "--from-tsv", str(tsv3), "--out", str(out)], capture_output=True, text=True, encoding="utf-8")
    check("movies reported", "Movies: have 1, missing 1" in r5.stdout, True)
    check("movies not downloaded without --include-movies", Path(f"{out}-missing.txt").read_text(encoding="utf-8"), "")
    subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                    "--from-tsv", str(tsv3), "--out", str(out), "--include-movies"], capture_output=True, text=True, encoding="utf-8")
    check("--include-movies: the missing movie only", Path(f"{out}-missing.txt").read_text(encoding="utf-8").split(),
          ["https://www.patreon.com/posts/302"])
    Path(root, "Creator A", "Movies", "Interstellar (2014).mp4").unlink()
    Path(root, "Creator A", "Movies").rmdir()
    check("--include-new: new show not in review", "Mr. Robot" in Path(f"{out}-review.txt").read_text(encoding="utf-8"), False)
    # default: only full-length posts count when the creator marks them; edited / short versions are skipped
    tsv2 = Path(tmp, "versions.tsv")
    tsv2.write_text("".join("\t".join(p) + "\n" for p in [
        ("201", "Full Length ｜ Vinland Saga ｜ 1x5", "https://www.patreon.com/posts/201"),
        ("202", "Edited ｜ Vinland Saga ｜ 1x6", "https://www.patreon.com/posts/202"),
        ("203", "WHAT IS HE DOING?! ｜ VINLAND SAGA ｜ Reaction 1x7", "https://www.patreon.com/posts/203"),
    ]), encoding="utf-8")
    r3 = subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                         "--from-tsv", str(tsv2), "--out", str(out)], capture_output=True, text=True, encoding="utf-8")
    check("only the full-length post is missing", Path(f"{out}-missing.txt").read_text(encoding="utf-8").split(),
          ["https://www.patreon.com/posts/201"])
    check("skipped versions reported", "2 edited / short posts skipped" in r3.stdout, True)
    r4 = subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                         "--from-tsv", str(tsv2), "--out", str(out), "--all-versions"], capture_output=True, text=True, encoding="utf-8")
    check("--all-versions counts them (show from the segment before the episode)",
          sorted(Path(f"{out}-missing.txt").read_text(encoding="utf-8").split()),
          [f"https://www.patreon.com/posts/{i}" for i in (201, 202, 203)])

# Streaming listing + resume, with a fake yt-dlp on PATH (POSIX only: Windows won't run a script named "yt-dlp")
if sys.platform != "win32":
    import os
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp, "yt-dlp")
        # prints three posts, skipping ids listed in a --download-archive file (like yt-dlp does)
        fake.write_text(f"""#!{sys.executable}
import sys
args = sys.argv[1:]
skip = set()
if "--download-archive" in args:
    skip = {{l.split()[1] for l in open(args[args.index("--download-archive") + 1]) if l.strip()}}
for i in ("201", "202", "203"):
    if i not in skip:
        print(f"{{i}}\\tShow ｜ 1x{{i[-1]}}\\thttps://www.patreon.com/posts/{{i}}", flush=True)
""", encoding="utf-8")
        fake.chmod(0o755)
        os.environ["PATH"] = tmp + os.pathsep + os.environ["PATH"]
        sys.path.insert(0, str(HERE))
        import reaction_gaps as rg
        tsv = Path(tmp, "listing.tsv")
        tsv.write_text("201\tShow ｜ 1x1\thttps://www.patreon.com/posts/201\n", encoding="utf-8")   # an earlier, interrupted run
        posts = rg.list_posts(url="https://example.invalid/posts", save_tsv=str(tsv), every=1)
        check("resume keeps the earlier post and adds the rest", [p[0] for p in posts], ["201", "202", "203"])
        check("tsv holds every post once", [l.split("\t")[0] for l in tsv.read_text(encoding="utf-8").splitlines()],
              ["201", "202", "203"])
        check("temporary archive removed", Path(f"{tsv}.known").exists(), False)

print(f"\n{'ALL PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
