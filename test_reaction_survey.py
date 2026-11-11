"""Test for reaction_survey.py: a throw-away library; checks the findings and that nothing is changed.
    python test_reaction_survey.py
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import reaction_survey as rs  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else f"\n     got  {got!r}\n     want {want!r}")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp, "reaction")
    big = b"x" * (2 * 2**20)                               # "finished" at --min-mb 1
    files = {
        "Some Creator/Show A/Show A - S01E01.mp4": big,
        "Some Creator/Show A/Show A - S01E02-03.mp4": big,
        "Some Creator/Show A/Season 01/Show A - S01E03.mkv": big,      # duplicate of E03 in the range file
        "Some Creator/Show A/SA 1x4 [123456].mp4": big,                # not library naming
        "Some Creator/Show A/Show A - S01E05.mp4": b"x",               # cut-off download
        "Some Creator/Show A/SA 1x6 [123457].mp4.part": b"x",
        "Some Creator/Show A/cover.jpg": b"x",
        "Some Creator/Movies/Some Movie (2014).mp4": big,              # movie titles are fine
        "Some Creator/loose episode.mp4": big,
        "SomeCreator/Show B/Show B - S01E01.mp4": big,                 # the same creator under a second spelling
        "Other Creator/Show A/Show A - S01E01.mp4": big,               # not surveyed
    }
    for name, content in files.items():
        path = Path(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    Path(root, "Some Creator", "Empty Show").mkdir()
    before = sorted((str(p), p.stat().st_size if p.is_file() else -1) for p in root.rglob("*"))

    folders, shows, findings = rs.survey(root, "some creator", min_mb=1)
    names = lambda section: sorted(path.name for _, path in findings[section])
    check("both spellings of the creator are found", [f.name for f in folders], ["Some Creator", "SomeCreator"])
    check("per show: files and library naming", (shows["Show A"][0], shows["Show A"][2]), (7, 4))
    check("unfinished: .part and the tiny video", names("unfinished"), ["SA 1x6 [123457].mp4.part", "Show A - S01E05.mp4"])
    check("duplicates: the range file and the single episode", names("duplicates"), ["Show A - S01E02-03.mp4", "Show A - S01E03.mkv"])
    check("naming: only the file with a post id", names("naming"), ["SA 1x4 [123456].mp4"])
    check("loose files", names("loose files"), ["loose episode.mp4"])
    check("not video", names("not video"), ["cover.jpg"])
    check("empty folders", names("empty"), ["Empty Show"])
    after = sorted((str(p), p.stat().st_size if p.is_file() else -1) for p in root.rglob("*"))
    check("the library is untouched", after, before)

print(f"\n{'ALL PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
