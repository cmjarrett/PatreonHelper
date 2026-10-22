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
- **Faster and more complete: list from Patreon's public API** with `--patreon https://www.patreon.com/<name>` instead of `--url`: every video post with its collection in seconds (~30 requests for 3,000 posts), no login, no yt-dlp. Posts your tier can't open are listed too (the download skips them with "no access"), and audio posts are left out. The listing is saved with `--save-tsv` as usual, the collections to `<out>-collections.json`.
- **Collections decide the show.** With `--patreon` (or `--collections-from <creator URL>` on a yt-dlp listing) the Patreon collection's name, minus "Reaction", is the show, through the aliases, so creators who name posts by abbreviation (`HY 2x14`, `VM 4x12`) sort correctly. Grab-bag collections ("All other shows!", polls, sketches) are ignored. `--only-collections "The Office,Severance"` keeps only those collections, for a creator where you want a few shows. For creators without usable collections, `--collections <folder>` takes hand-made `<Show>.txt` URL lists instead.
- **Full vs edited, per creator:** `Full Length` / `Unedited` / `Uncut` always mean the full reaction, `Edited |` and `(Cut Reaction)` the edited one, and a collection's name counts for its posts ("Severance (Full Length)", "Game Of Thrones (Early Access)"). Creators with their own words get `--full-marker "watch along"` / `--cut-marker "early access"`, and `--unmarked full` when it's the edited posts that are marked (Diegesis) rather than the full ones (Emme). In the creators JSON: `full_markers`, `cut_markers`, `unmarked`.
- **All creators at once:** `python .\reaction_gaps_all.py --creators <your creators JSON> --root ... --aliases ...` runs the above per creator (handling `patreon` / `collections`, optional `include` list of collections), prints each creator's collections with post counts, and ends with the `Download-Creator.ps1` command per creator. Nothing is downloaded.

### 2. File them: `reaction_rename.py`
```powershell
python .\reaction_rename.py --root "\nas\media\reaction" --src C:\patreon\inbox             # dry run
python .\reaction_rename.py --root "\nas\media\reaction" --src C:\patreon\inbox --apply
python .\reaction_rename.py --root "\nas\media\reaction" --tidy                             # rename what's already in the library
```
- Understands Patreon titles (`Show ｜ S2 x E12-15 ｜ Unedited Reaction [123]`, `Full Length ｜ Show ｜ 2x9`, `Show S1 E17 - Title (Uncut Reaction)` (its `(Cut Reaction)` twin is the edited one), `Episode 3`, `S01e08`, `Show | Season 4 | Ep. 3`, `Stranger Things 4 | Ep. 3` (a trailing digit on the show name is the season), `Title (Full Movie Reaction)` …) and files them into the existing show folder, matching its naming and season folders.
- **Never overwrites**; downloads whose episodes are already there (also as single-episode files) are skipped; movies, trailers, openings, odd ranges and unknown shows are listed for review and left alone.
- The creator comes from the inbox folder (or `--creator`); `--new-shows` creates folders for shows the library doesn't have yet; creators with a `Movies` folder get `Movies\<title>.ext`.
- Show-name aliases: copy `reaction-aliases.example.json` to `reaction-aliases.json` (git-ignored) and add your own, or pass `--aliases <file>`.
- Tests: `python test_reaction_rename.py` (a throw-away fake library; touches nothing real).
