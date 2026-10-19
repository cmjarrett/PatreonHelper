# PatreonHelper
Helper for Patreon users


This tool is a wrapper around the YT-DLP tool is intended to help mostly non-technical users make copies of patreon videos.  
This repo is mostly centered around 'collections' of videos, but the Download-Playlist-From-Patreon can perform simple bulk downloads.

There is one-time manual work of going to the Patreon Collection url and retrieving one inner Node from the Browser Inspector.

You need to have this installed:

YT-DLP: https://github.com/yt-dlp/yt-dlp

As a user you need to:
 * Download the two scripts and place them in your working directory
 
        C:\patreon will be used as the base directory for this entire workflow example
 * Login to Patreon using your browser of choice
 
        The scripts are configured for FireFox but should work for any browser with a one line change
 * Go to the Collection you wish to download 
   
        For Example it would look like this, https://www.patreon.com/collection/11111111111111?view=expanded
 * Make Sure EVERY video you want to download is visible on the page.
 
        For Large Collections you will often have to hit 'expand' to load the entire collection.
        For Mixed Collections you can use the Search/Filter part of the collection to narrow the videos if you don't want all of them
 * Press Ctrl+Shift+I to go to the 'Browser Inspector'
 * Right Click the top-level node and copy->Inner HTML
 
        For users with little technical knowledge, in the Browser Inspector if you hover over a node with your mouse the element will be 'highlighted'.
        The Top-Level element is usually at the top of the page and is in a <HTML> right below <!DOCTYPE
        Right-click the <HTML> node and the Copy->Inner HTML option is what you want to grab all of the page
 * Paste in your desired temp file.  
 
       I typically do something like 'C:\patreon\deathnote_blahcreator.txt'
 * Open up a powershell window in your working directory (C:\patreon)
 * >.\Clean-Patreon-PlayList-HTML.ps1 -FileName:C:\patreon\deathnote_blahcreator.txt
   
       This will spit out a clean list of URLs.  Paste that into another file for the next portion (e.g. C:\patreon\deathnote_clean.txt)
 * >.\Download-Playlist-From-Patreon.ps1 -FileName:C:\patreon\\deathnote_clean.txt -browser:firefox

       This downloads using YT-DLP the entire collection at best video preference.
       If you need to use a different browser than Firefox replace FireFox in the script with your browser of choice.  
       All browsers supported by YT-DLP are part of the possible inputs--you can use tab to complete.


## Reaction library tools

For keeping a Plex/Jellyfin library of reaction videos (`<Library>/<Creator>/<Show>/<Show> - S01E08.ext`) fed from Patreon.
Needs [yt-dlp](https://github.com/yt-dlp/yt-dlp) (`winget install yt-dlp.yt-dlp`) and Python 3.10+.

### 1. Download a creator: `Download-Creator.ps1`
```powershell
.\Download-Creator.ps1 -Creator "Some Creator" -Url https://www.patreon.com/c/<name>/posts -Preview   # list only
.\Download-Creator.ps1 -Creator "Some Creator" -Url https://www.patreon.com/c/<name>/posts
.\Download-Creator.ps1 -Creator "Some Creator" -ListFile C:\patreon\show_clean.txt -Match "Show Name"
```
- `-Creator` is the folder name the videos belong to in your library; downloads go to `C:\patreon\inbox\<Creator>\`.
- `-Url` (a creator's page) downloads **every post**, so it also works for creators without collections; posts without video are skipped. yt-dlp can't read collection pages, so for a collection use the cleaned URL list from `Clean-Patreon-PlayList-HTML.ps1` with `-ListFile`.
- A shared download archive (`C:\patreon\downloaded.txt`) remembers what was fetched: subscribe, download, unsubscribe, and a later re-subscribe only gets new posts.
- Optional: `-Match <regex>` (titles), `-After YYYYMMDD`, `-Browser` (default firefox), `-Inbox`, `-Archive`.

### 1b. Complete a collection: find the gaps first, `reaction_gaps.py`
Library files are renamed (no post id left), so downloading a creator's whole feed would re-download everything you own.
List the creator's posts (titles only, nothing downloaded) and compare them with the library first:
```powershell
python .\reaction_gaps.py --root "\\nas\media\reaction" --creator "Some Creator" --url https://www.patreon.com/c/<name>/posts --save-tsv posts.tsv
python .\reaction_gaps.py --root "\\nas\media\reaction" --creator "Some Creator" --from-tsv posts.tsv --show "Some Show"
.\Download-Creator.ps1 -Creator "Some Creator" -ListFile gaps-missing.txt
```
- Report per show: **have / missing / partial / new show / other** (movies, trailers); `gaps-missing.txt` holds only the posts to download, `gaps-review.txt` the ones to look at.
- `--include-partial` adds posts that are only partly in the library; `--list-file` takes a collection's URL list instead of `--url`.
- `--seed-archive C:\patreon\downloaded.txt` writes the posts you already have into yt-dlp's download archive, so later full-creator runs skip them on their own.
- Listing a big creator takes a while (yt-dlp reads each post); `--save-tsv` / `--from-tsv` avoid repeating it.

### 1c. All creators in one go: `Sync-Reactions.ps1`
Once a few creators are set up, one command lists, compares and downloads for all of them. Describe them in a creators file (copy `reaction-creators.example.json`; keep your real one outside this repo):
```powershell
.\Sync-Reactions.ps1 -Config C:\private\reaction-creators.json -Root "\\nas\media\reaction" -Aliases C:\private\reaction-aliases.json -ReportOnly
.\Sync-Reactions.ps1 -Config C:\private\reaction-creators.json -Root "\\nas\media\reaction" -Aliases C:\private\reaction-aliases.json
.\Sync-Reactions.ps1 ... -Import          # then -Import -Apply: files the downloads with reaction_rename.py
```
- Per creator: `reaction_gaps.py` (listing saved in `sync-state\`, so later runs only read **new** posts) → the missing posts → `Download-Creator.ps1`. New shows and movies are included unless a creator sets `"new_shows": false` / `"movies": false`.
- **Download categories:** you don't have to mirror everything. `"include": ["Game of Thrones", "Severance"]` downloads only posts whose title (or show, through the aliases) matches; `"exclude": ["One Piece"]` never downloads those (exclude wins). `_defaults` applies to every creator. `-Include` / `-Exclude` set them for one run.
- `-Offline` re-checks the saved listings without asking Patreon (seconds): handy after changing the categories. `-Creator "Some Creator"` runs just one.
- The same filters exist on `reaction_gaps.py` as `--only` / `--skip` (repeatable).
- Test: `pwsh ./test_sync_reactions.ps1`.

### 2. File them: `reaction_rename.py`
```powershell
python .\reaction_rename.py --root "\nas\media\reaction" --src C:\patreon\inbox             # dry run
python .\reaction_rename.py --root "\nas\media\reaction" --src C:\patreon\inbox --apply
python .\reaction_rename.py --root "\nas\media\reaction" --tidy                             # rename what's already in the library
```
- Understands Patreon titles (`Show ｜ S2 x E12-15 ｜ Unedited Reaction [123]`, `Full Length ｜ Show ｜ 2x9`, `Episode 3`, `S01e08` …) and files them into the existing show folder, matching its naming and season folders.
- **Never overwrites**; downloads whose episodes are already there (also as single-episode files) are skipped; movies, trailers, openings, odd ranges and unknown shows are listed for review and left alone.
- The creator comes from the inbox folder (or `--creator`); `--new-shows` creates folders for shows the library doesn't have yet; creators with a `Movies` folder get `Movies\<title>.ext`.
- Show-name aliases: copy `reaction-aliases.example.json` to `reaction-aliases.json` (git-ignored) and add your own, or pass `--aliases <file>`.
- Tests: `python test_reaction_rename.py` (a throw-away fake library; touches nothing real).
