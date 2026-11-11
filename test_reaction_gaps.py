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
    tsv.write_text("".join("\t".join(p) + "\n" for p in posts), encoding="utf-8", errors="replace")
    arch = Path(tmp, "downloaded.txt")
    arch.write_text("patreon 104\n", encoding="utf-8", errors="replace")
    out = Path(tmp, "gaps")
    r = subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                        "--from-tsv", str(tsv), "--out", str(out), "--seed-archive", str(arch), "--all-versions"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")   # a stray console-page byte must not kill the run
    print(r.stdout if fails else "", r.stderr[-800:])
    missing = Path(f"{out}-missing.txt").read_text(encoding="utf-8", errors="replace").split()
    check("missing list = the two absent Vinland posts", sorted(missing),
          ["https://www.patreon.com/posts/102", "https://www.patreon.com/posts/103"])
    check("partial not in missing by default", "https://www.patreon.com/posts/105" in missing, False)
    review = Path(f"{out}-review.txt").read_text(encoding="utf-8", errors="replace")
    check("new show (title with a dot) -> review", "new show\tMr. Robot" in review, True)
    check("trailer -> review", "Infinity Castle" in review, True)
    check("report shows Vinland counts", "Vinland Saga: have 2, missing 2" in r.stdout, True)
    check("report shows the partial", "partial: S02E10-13 (has E10,E11)" in r.stdout, True)
    a = arch.read_text(encoding="utf-8", errors="replace").split("\n")
    check("archive seeded with owned posts, no duplicates", sorted(x for x in a if x),
          ["patreon 101", "patreon 104", "patreon 108"])
    r2 = subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                         "--from-tsv", str(tsv), "--out", str(out), "--include-partial", "--show", "Demon Slayer"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    m2 = Path(f"{out}-missing.txt").read_text(encoding="utf-8", errors="replace").split()
    check("--show + --include-partial", m2, ["https://www.patreon.com/posts/105"])
    subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                    "--from-tsv", str(tsv), "--out", str(out), "--all-versions", "--include-new"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("--include-new adds the new show", "https://www.patreon.com/posts/106" in
          Path(f"{out}-missing.txt").read_text(encoding="utf-8", errors="replace").split(), True)
    # movies: compared with <creator>/Movies; only --include-movies puts the missing ones in the list
    Path(root, "Creator A", "Movies").mkdir()
    Path(root, "Creator A", "Movies", "Interstellar (2014).mp4").write_bytes(b"x")
    tsv3 = Path(tmp, "movies.tsv")
    tsv3.write_text("".join("\t".join(p) + "\n" for p in [
        ("301", "Interstellar ｜ Unedited Reaction", "https://www.patreon.com/posts/301"),
        ("302", "Jaws ｜ Unedited Reaction", "https://www.patreon.com/posts/302"),
        ("303", "Infinity Castle ｜ Trailer ｜ Unedited Reaction", "https://www.patreon.com/posts/303"),
    ]), encoding="utf-8", errors="replace")
    r5 = subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                         "--from-tsv", str(tsv3), "--out", str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("movies reported", "Movies: have 1, missing 1" in r5.stdout, True)
    check("movies not downloaded without --include-movies", Path(f"{out}-missing.txt").read_text(encoding="utf-8", errors="replace"), "")
    subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                    "--from-tsv", str(tsv3), "--out", str(out), "--include-movies"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("--include-movies: the missing movie only", Path(f"{out}-missing.txt").read_text(encoding="utf-8", errors="replace").split(),
          ["https://www.patreon.com/posts/302"])
    Path(root, "Creator A", "Movies", "Interstellar (2014).mp4").unlink()
    Path(root, "Creator A", "Movies").rmdir()
    check("--include-new: new show not in review", "Mr. Robot" in Path(f"{out}-review.txt").read_text(encoding="utf-8", errors="replace"), False)
    # default: only full-length posts count when the creator marks them; edited / short versions are skipped
    tsv2 = Path(tmp, "versions.tsv")
    tsv2.write_text("".join("\t".join(p) + "\n" for p in [
        ("201", "Full Length ｜ Vinland Saga ｜ 1x5", "https://www.patreon.com/posts/201"),
        ("202", "Edited ｜ Vinland Saga ｜ 1x6", "https://www.patreon.com/posts/202"),
        ("203", "WHAT IS HE DOING?! ｜ VINLAND SAGA ｜ Reaction 1x7", "https://www.patreon.com/posts/203"),
    ]), encoding="utf-8", errors="replace")
    r3 = subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                         "--from-tsv", str(tsv2), "--out", str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("only the full-length post is missing", Path(f"{out}-missing.txt").read_text(encoding="utf-8", errors="replace").split(),
          ["https://www.patreon.com/posts/201"])
    check("skipped versions reported", "2 edited / short posts skipped" in r3.stdout, True)
    r4 = subprocess.run([sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                         "--from-tsv", str(tsv2), "--out", str(out), "--all-versions"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("--all-versions counts them (show from the segment before the episode)",
          sorted(Path(f"{out}-missing.txt").read_text(encoding="utf-8", errors="replace").split()),
          [f"https://www.patreon.com/posts/{i}" for i in (201, 202, 203)])

# The download record and the never-keep list: what was fetched once, or is never wanted, stays out of the list
# whatever the library holds
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp, "reaction")
    Path(root, "Creator A", "Vinland Saga").mkdir(parents=True)
    Path(root, "Creator A", "Vinland Saga", "Vinland Saga - S01E01.mp4").write_bytes(b"x")
    tsv = Path(tmp, "posts.tsv")
    tsv.write_text("".join("\t".join(p) + "\n" for p in [
        ("401", "Vinland Saga ｜ 1x1", "https://www.patreon.com/posts/401"),      # have
        ("402", "Vinland Saga ｜ 1x2", "https://www.patreon.com/posts/402"),      # fetched once, deleted since
        ("403", "Vinland Saga ｜ 1x3", "https://www.patreon.com/posts/403"),      # really missing
        ("404", "Dull Show ｜ 1x1", "https://www.patreon.com/posts/404"),         # never keep
        ("405", "Other Show ｜ 1x1", "https://www.patreon.com/posts/405"),        # new show, wanted
    ]), encoding="utf-8")
    arch = Path(tmp, "downloaded.txt")
    arch.write_text("patreon 402\nyoutube abcdefghijk", encoding="utf-8")        # no final newline, like a cut-off file
    never = Path(tmp, "never-keep.txt")
    out = Path(tmp, "gaps")
    ledger_cmd = [sys.executable, str(HERE / "reaction_ledger.py")]
    gaps_cmd = [sys.executable, str(HERE / "reaction_gaps.py"), "--root", str(root), "--creator", "Creator A",
                "--from-tsv", str(tsv), "--out", str(out), "--include-new", "--archive", str(arch),
                "--seed-archive", str(arch), "--never-file", str(never)]
    run = lambda cmd: subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    listed = lambda: sorted(u.rsplit("/", 1)[1] for u in Path(f"{out}-missing.txt").read_text(encoding="utf-8").split())

    r = run(ledger_cmd + ["never", "Creator A", "Dull Show", "--file", str(never)])
    check("never: entry added", "added to" in r.stdout, True)
    r = run(gaps_cmd)
    check("fetched-before and never-keep posts are not listed", listed(), ["403", "405"])
    check("report counts what was left out", "left out: 1 fetched before" in r.stdout and "1 on the never-keep list" in r.stdout, True)
    check("owned post seeded, record keeps its lines", sorted(arch.read_text(encoding="utf-8").split("\n")),
          ["", "patreon 401", "patreon 402", "youtube abcdefghijk"])

    # the owner deletes the episode from the library: it must not come back
    Path(root, "Creator A", "Vinland Saga", "Vinland Saga - S01E01.mp4").unlink()
    run(gaps_cmd)
    check("deleted from the library after a run: still not listed", listed(), ["403", "405"])

    run(ledger_cmd + ["never", "Creator A", "--file", str(never)])              # the whole creator
    run(gaps_cmd)
    check("never: whole creator", listed(), [])
    run(ledger_cmd + ["never", "Creator A", "--file", str(never), "--remove"])
    run(gaps_cmd)
    check("never --remove brings the creator back, the show stays out", listed(), ["403", "405"])
    r = run(gaps_cmd + ["--never", "Other Show"])
    check("--never on the command line", listed(), ["403"])

    # seeding: finished files in an inbox, and a URL list
    inbox = Path(tmp, "inbox", "Creator A")
    inbox.mkdir(parents=True)
    for name in ("Vinland Saga ｜ 1x3 [403].mp4", "Embedded video [abcdefghijk].mp4", "Half done [405].mp4.part",
                 "No id here.mp4"):
        Path(inbox, name).write_bytes(b"x")
    r = run(ledger_cmd + ["seed", "--archive", str(arch), "--inbox", str(inbox.parent), "--dry-run"])
    check("seed --dry-run writes nothing", "patreon 403" in arch.read_text(encoding="utf-8"), False)
    r = run(ledger_cmd + ["seed", "--archive", str(arch), "--inbox", str(inbox.parent)])
    check("seed --inbox: finished files only, known lines not repeated", "added 1 to" in r.stdout, True)
    run(gaps_cmd)
    check("seeded from the inbox: not listed again (the .part file is)", listed(), ["405"])
    urls = Path(tmp, "old-list.txt")
    urls.write_text("https://www.patreon.com/posts/other-show-1x1-405?utm=x\nhttps://www.patreon.com/posts/406\n"
                    "patreon 407\n408000\nnot a post\n", encoding="utf-8")
    r = run(ledger_cmd + ["seed", "--archive", str(arch), "--ids-from", str(urls)])
    check("seed --ids-from: URLs with a title slug, bare URLs, record lines, bare ids", "added 4 to" in r.stdout, True)
    run(gaps_cmd)
    check("everything fetched or seeded: nothing to download", listed(), [])
    r = run(ledger_cmd + ["status", "--archive", str(arch), "--file", str(never)])
    check("status", "8 entries (patreon 7, youtube 1)" in r.stdout and "Creator A | Dull Show" in r.stdout, True)

    # reaction_gaps_all: exclude from the creators file, "sync": false, the plan, and the unreachable-library stop
    import json
    cfg = Path(tmp, "creators.json")
    cfg.write_text(json.dumps({
        "_defaults": {"exclude": ["Other Show"]},
        "Creator A": {"url": "https://www.patreon.com/a", "handling": "patreon"},
        "Creator B": {"url": "https://www.patreon.com/b", "handling": "patreon", "sync": False},
    }), encoding="utf-8")
    state = Path(tmp, "state")
    state.mkdir()
    (state / "creatora.tsv").write_text(tsv.read_text(encoding="utf-8"), encoding="utf-8")
    arch.write_text("", encoding="utf-8")
    Path(root, "Creator A", "Vinland Saga", "Vinland Saga - S01E01.mp4").write_bytes(b"x")
    all_cmd = [sys.executable, str(HERE / "reaction_gaps_all.py"), "--creators", str(cfg), "--out-dir", str(state),
               "--archive", str(arch), "--never-file", str(never), "--offline"]
    r = run(all_cmd + ["--root", str(root)])
    plan = json.loads((state / "sync-plan.json").read_text(encoding="utf-8"))
    check("plan: one creator, exclude + never-keep applied", [(p["creator"], p["count"]) for p in plan], [("Creator A", 2)])
    check("sync false is left out", '-- Creator B: left out ("sync": false)' in r.stdout, True)
    check("the run seeds the owned post", "patreon 401" in arch.read_text(encoding="utf-8"), True)
    r = run(all_cmd + ["--root", str(Path(tmp, "not-mounted"))])
    check("unreachable library: stops, lists nothing", r.returncode != 0 and "not reachable" in r.stderr, True)

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
""", encoding="utf-8", errors="replace")
        fake.chmod(0o755)
        os.environ["PATH"] = tmp + os.pathsep + os.environ["PATH"]
        sys.path.insert(0, str(HERE))
        import reaction_gaps as rg
        tsv = Path(tmp, "listing.tsv")
        tsv.write_text("201\tShow ｜ 1x1\thttps://www.patreon.com/posts/201\n", encoding="utf-8", errors="replace")   # an earlier, interrupted run
        posts = rg.list_posts(url="https://example.invalid/posts", save_tsv=str(tsv), every=1)
        check("resume keeps the earlier post and adds the rest", [p[0] for p in posts], ["201", "202", "203"])
        check("tsv holds every post once", [l.split("\t")[0] for l in tsv.read_text(encoding="utf-8", errors="replace").splitlines()],
              ["201", "202", "203"])
        check("temporary archive removed", Path(f"{tsv}.known").exists(), False)

print(f"\n{'ALL PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
