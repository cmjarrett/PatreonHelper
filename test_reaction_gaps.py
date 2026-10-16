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
                        "--from-tsv", str(tsv), "--out", str(out), "--seed-archive", str(arch)],
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

print(f"\n{'ALL PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
