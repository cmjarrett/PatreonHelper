"""Tests for reaction_rename.py against real-world file names (Patreon titles and hand-renamed library files). Builds a throw-away fake library of empty files; touches nothing real.
    python scripts/media/test_reaction_rename.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import reaction_rename as rr  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"\n     got  {got}\n     want {want}")


def ep(name):
    i = rr.parse(name)
    if i is None:
        return "conventional"
    if "season" not in i:
        return ("review", i["hint"])
    return (i["hint"], i["season"], i["e1"], i["e2"], i["special"])


# --- parser: raw Patreon titles seen in the downloads and the library
check("S2 x E12-15", ep("Demon Slayer： Kimetsu no Yaiba ｜ S2 x E12-15 ｜ Unedited Reaction [155355918].mp4"), ("Demon Slayer", 2, 12, 15, False))
check("S1 x E13-16", ep("Demon Slayer ｜ S1 x E13-16 ｜ Unedited Reaction [152326217].mp4"), ("Demon Slayer", 1, 13, 16, False))
check("S3 X E1-4", ep("Demon Slayer： Kimetsu no Yaiba ｜ S3 X E1-4 ｜ Unedited Reaction [156478288].mp4"), ("Demon Slayer", 3, 1, 4, False))
check("FINALE word", ep("Demon Slayer ｜ S1 x E25-26 [FINALE] ｜ Unedited Reaction [153960189].mkv"), ("Demon Slayer", 1, 25, 26, False))
check("joke suffix", ep("Demon Slayer： Kimetsu no Yaiba ｜ S4 X E5-7 (yes, that's correct lol) ｜ Unedited Reaction [158990969].mp4"), ("Demon Slayer", 4, 5, 7, False))
check("E4 + E8", ep("Demon Slayer： Kimetsu no Yaiba ｜ S4 X E4 + E8 FINALE ｜ Unedited Reaction [159731254].mp4")[0], "review")
check("movie", ep("Demon Slayer： Kimetsu no Yaiba ｜ The Movie： Mugen Train ｜ Unedited Reaction [154005636].mkv")[0], "review")
check("trailer", ep("Infinity Castle ｜ Trailer Reaction [159738609].mp4")[0], "review")
check("opening", ep("Opening⧸Ending Mugen Train Arc Reaction [154598323].mp4")[0], "review")
check("4x15", ep("Full Length ｜ Haikyuu ｜ 4x15 [165975078].mp4"), ("Haikyuu", 4, 15, None, False))
check("2x9", ep("Full Length ｜ Arcane ｜ 2x9 [116609382].mp4"), ("Arcane", 2, 9, None, False))
check("1X08", ep("Full Length ｜ Arcane ｜ 1X08 [88824133].mp4"), ("Arcane", 1, 8, None, False))
check("Episode 5", ep("Full Length ｜ Chernobyl ｜ Episode 5 [90922226].mp4"), ("Chernobyl", 1, 5, None, False))
check("S01e08", ep("Jujutsu Kaisen ｜ S01e08 [108790195].mp4"), ("Jujutsu Kaisen", 1, 8, None, False))
check("S01E06 no id", ep("Jujutsu Kaisen ｜ S01E06.mp4"), ("Jujutsu Kaisen", 1, 6, None, False))
check("JJK 2x15", ep("JJK 2x15 [111750545].mp4"), ("JJK", 2, 15, None, False))
check("Loki unpadded", ep("Loki - S02E3-4.mp4"), ("Loki", 2, 3, 4, False))
check("Dumpster Battle", ep("Full Length ｜ Haikyuu ｜ The Dumpster Battle [168692595].mp4")[0], "review")
check("episode title first", ep("THE BOSS ｜ MOB PSYCHO 100 ｜ Reaction 2x11 [1].mp4"), ("MOB PSYCHO 100", 2, 11, None, False))
check("empty first segment", ep("｜ CODE GEASS ｜ Reaction 1x10.mp4"), ("CODE GEASS", 1, 10, None, False))
check("subtitle before episode", ep("I RAISED THAT BOY ｜ KAGUYA SAMA ｜ Love Is War Reaction 1x5.mp4"), ("KAGUYA SAMA", 1, 5, None, False))
check("2x5 & 2x6", ep("Edited ｜ Frieren ｜ 2x5 & 2x6.mp4"), ("Frieren", 2, 5, 6, False))
check("absolute & pair", ep("Full Length ｜ One Piece ｜ 898 & 899.mp4"), ("One Piece", 1, 898, 899, False))
check("absolute range", ep("Full Length ｜ One Piece ｜ 869 - 871.mp4"), ("One Piece", 1, 869, 871, False))
check("absolute triple", ep("Full Length ｜ One Piece ｜ 234, 235, 236.mp4"), ("One Piece", 1, 234, 236, False))
check("Episodes N & M", ep("Full Length ｜ One Piece ｜ Episodes 17 & 18.mp4"), ("One Piece", 1, 17, 18, False))
check("list with a gap", ep("Full Length ｜ One Piece ｜ 55, 61 & 62.mp4")[0], "review")
check("absolute non-contiguous", ep("Full Length ｜ One Piece ｜ 894 & 897.mp4")[0], "review")
check("Full Lenth typo + Ep", ep("Full Lenth ｜ Erased ｜ Ep 7.mp4"), ("Erased", 1, 7, None, False))
check("live action is its own show", ep("Full Length ｜ One Piece ｜ Live Action 2x1.mp4"), ("One Piece Live Action", 2, 1, None, False))
check("live action short post", ep("SHE'S HERE ｜ ONE PIECE ｜ 2x1 Live Action Reaction.mp4"), ("ONE PIECE Live Action", 2, 1, None, False))
check("number in show name", ep("Full Length ｜ Mob Psycho 100 ｜ OVA Special.mp4")[0], "review")
check("full length", [rr.is_full_length(t) for t in ("Full Length ｜ Haikyuu ｜ 4x15", "Full Lenth ｜ Erased ｜ Ep 7",
      "Demon Slayer ｜ S1 x E13-16 ｜ Unedited Reaction", "Edited ｜ Frieren ｜ 2x5 & 2x6", "THE BOSS ｜ MOB PSYCHO 100 ｜ Reaction 2x11")],
      [True, True, True, False, False])
check("conventional", ep("Demon Slayer - S02E09.mp4"), "conventional")
check("conventional title", ep("The Last Of Us - S01E03 - Long, Long Time.mp4"), "conventional")
check("conventional range", ep("Jujutsu Kaisen - S03E11-12.mp4"), "conventional")

# --- end to end on a fake library
with tempfile.TemporaryDirectory() as tmp:
    root, src = Path(tmp, "reaction"), Path(tmp, "downloads")
    lib = {
        "Creator A/Demon Slayer": ["Demon Slayer - S01E01.mp4", "Demon Slayer - S02E08.mp4", "Demon Slayer - S02E09.mp4"],
        "Creator A/Haikyu": ["Haikyuu - S01E12.mp4", "Haikyuu - S04E16.mp4"],
        "Creator A/Arcane": ["Full Length ｜ Arcane ｜ 2x9 [116609382].mp4"],
        "Creator A/Jujutsu Kaisen/Season 01": ["Jujutsu Kaisen ｜ S01e08 [108790195].mp4", "Jujutsu Kaisen - S01E01.mp4"],
        "Creator A/Spy X Family": ["SpyxFamily - S01E08.mp4"],
        "Creator B/SpyxFamily": ["Spy × Family - S01E21-25.mp4"],
        "Creator B/Loki": ["Loki - S01E06.mkv", "Loki - S02E3-4.mp4"],
        "Creator C/JJK": ["JJK 2x15 [111750545].mp4"],
        "Creator D/Movies": ["Dune, 1984.mp4", "Dune Part Two.mkv"],
    }
    for d, files in lib.items():
        Path(root, d).mkdir(parents=True)
        for f in files:
            Path(root, d, f).write_bytes(b"x")
    src.mkdir()
    for f in ["Demon Slayer： Kimetsu no Yaiba ｜ S2 x E12-15 ｜ Unedited Reaction [155355918].mp4",
              "Full Length ｜ Haikyuu ｜ 4x15 [165975078].mp4",
              "Full Length ｜ Haikyuu ｜ 4x16 [166398882].mp4",
              "JJK 2x16 [111750546].mp4",
              "Spy x Family ｜ S2 x E1-3 [1].mp4",
              "Infinity Castle ｜ Trailer Reaction [159738609].mp4",
              "Demon Slayer ｜ S2 x E8-9 ｜ Unedited Reaction [2].mp4",
              "Demon Slayer ｜ S1 x E1-4 ｜ Unedited Reaction [3].mp4"]:
        Path(src, f).write_bytes(b"xx")
    run = lambda *args: subprocess.run([sys.executable, str(HERE / "reaction_rename.py"), "--root", str(root), *args],
                                       capture_output=True, text=True, encoding="utf-8").stdout
    out = run("--src", str(src))
    check("import: Demon Slayer range", "Creator A/Demon Slayer/Demon Slayer - S02E12-15.mp4" in out.replace("\\", "/"), True)
    check("import: range fully covered by single files -> SKIP", "already have S02E08, S02E09" in out, True)
    check("import: partial overlap -> REVIEW", "partly there already: has E01; missing E02, E03, E04" in out, True)
    check("import: Haikyu uses the folder's display name", "Creator A/Haikyu/Haikyuu - S04E15.mp4" in out.replace("\\", "/"), True)
    check("import: existing episode skipped", "SKIP" in out and "Haikyuu - S04E16.mp4" in out, True)
    check("import: JJK ambiguous -> review", "show exists under" in out and "JJK 2x16" in out, True)
    check("import: Spy x Family ambiguous -> review", out.count("show exists under") >= 2, True)
    check("import: trailer -> review", "Infinity Castle" in out and "REVIEW" in out, True)
    check("dry run moved nothing", len(list(src.iterdir())), 8)
    out = run("--src", str(src), "--creator", "Creator C")
    check("--creator places JJK", "Creator C/JJK/Jujutsu Kaisen - S02E16.mp4" in out.replace("\\", "/"), True)
    # yt-dlp per-creator folder names the creator
    Path(src, "Creator C").mkdir()
    Path(src, "Creator C", "JJK 2x17 [111750547].mp4").write_bytes(b"xx")
    out = run("--src", str(src))
    check("creator folder places JJK", "Creator C/JJK/Jujutsu Kaisen - S02E17.mp4" in out.replace("\\", "/"), True)
    Path(src, "Creator C", "JJK 2x17 [111750547].mp4").unlink()
    Path(src, "Creator C").rmdir()
    # sub/run/unsub: a creator new to the library, and a movie creator
    nc = Path(tmp, "inbox2")
    Path(nc, "New Creator").mkdir(parents=True)
    Path(nc, "New Creator", "Full Length ｜ Frieren ｜ 1x05 [9].mp4").write_bytes(b"xx")
    Path(nc, "Movie Creator").mkdir()
    Path(root, "Movie Creator", "Movies").mkdir(parents=True)
    Path(root, "Movie Creator", "Movies", "50 First Dates.mp4").write_bytes(b"x")
    Path(nc, "Movie Creator", "Dune： Part Two (2024) ｜ MOVIE REACTION ｜ First Time Watching [7].mp4").write_bytes(b"xx")
    Path(nc, "Movie Creator", "50 First Dates (2004) ｜ Movie Reaction [8].mp4").write_bytes(b"xx")
    out = run("--src", str(nc)).replace("\\", "/")
    check("new creator: show needs --new-shows", "re-run with --new-shows" in out, True)
    check("movie creator: new movie -> Movies/<title>", "Movie Creator/Movies/Dune - Part Two (2024).mp4" in out, True)
    check("movie creator: existing title skipped", "movie already there" in out, True)
    out = run("--src", str(nc), "--new-shows").replace("\\", "/")
    check("--new-shows creates the show folder", "New Creator/Frieren/Frieren - S01E05.mp4" in out, True)
    run("--src", str(nc), "--new-shows", "--apply")
    check("--new-shows --apply placed it", Path(root, "New Creator", "Frieren", "Frieren - S01E05.mp4").exists(), True)
    check("movie --apply placed it", Path(root, "Movie Creator", "Movies", "Dune - Part Two (2024).mp4").exists(), True)

    out = run("--tidy")
    o = out.replace("\\", "/")
    check("tidy: movie folders left alone", "Dune" not in o and "4 in movie folders left" in o, True)
    check("tidy: Arcane", "Creator A/Arcane/Arcane - S02E09.mp4" in o, True)
    check("tidy: JJK season folder", "Creator A/Jujutsu Kaisen/Season 01/Jujutsu Kaisen - S01E08.mp4" in o, True)
    check("tidy: Loki padding", "Creator B/Loki/Loki - S02E03-04.mp4" in o, True)
    check("tidy: Creator C JJK via alias display", "Creator C/JJK/Jujutsu Kaisen - S02E15.mp4" in o, True)
    run("--tidy", "--apply")
    check("tidy --apply renamed Arcane", Path(root, "Creator A/Arcane/Arcane - S02E09.mp4").exists(), True)
    out = run("--src", str(src), "--apply")
    check("import --apply moved Demon Slayer", Path(root, "Creator A/Demon Slayer/Demon Slayer - S02E12-15.mp4").exists(), True)
    check("import --apply left reviews alone", Path(src, "Infinity Castle ｜ Trailer Reaction [159738609].mp4").exists(), True)

print(f"\n{'ALL PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
