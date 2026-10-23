<#
.SYNOPSIS
  Download a Patreon creator's reaction videos into an inbox folder named after the library's creator folder,
  then file them with reaction_rename.py (see README).

.DESCRIPTION
  Uses yt-dlp with the Patreon login from your browser (nothing stored by this script). Two sources:
    -Url       a creator's page, e.g. https://www.patreon.com/c/<name>/posts : every post, also for creators
               without collections (e.g. creators without collections). Text/image posts are skipped (yt-dlp: "no media").
    -ListFile  a list of post URLs, e.g. from PatreonHelper's Clean-Patreon-PlayList-HTML.ps1 (collections;
               yt-dlp can't read collection pages itself).
  -Creator is the library folder the videos belong to (Reaction\<Creator>\...), e.g. "Movie Creator"; it
  becomes the inbox sub-folder, so the renamer knows the creator even for a new one.
  A shared download archive remembers every post already fetched: subscribe, run, unsubscribe, and a later run
  never downloads the same post twice.

.EXAMPLE
  .\patreon_download.ps1 -Creator "Movie Creator" -Url https://www.patreon.com/c/<name>/posts -Preview
  .\patreon_download.ps1 -Creator "Movie Creator" -Url https://www.patreon.com/c/<name>/posts
  .\patreon_download.ps1 -Creator "Creator A" -ListFile C:\patreon\vinland_clean.txt -Match "Vinland"
  python .\reaction_rename.py --root "\\nas\media\reaction" --src C:\patreon\inbox            # dry run
  python .\reaction_rename.py --root "\\nas\media\reaction" --src C:\patreon\inbox --apply
#>
param(
    [Parameter(Mandatory = $true)] [string] $Creator,
    [string] $Url,
    [string] $ListFile,
    [string] $Match,                                    # only titles matching this regex (case-insensitive)
    [string] $After,                                    # only posts on/after this date, YYYYMMDD
    [string] $Inbox = 'C:\patreon\inbox',
    [string] $Archive = 'C:\patreon\downloaded.txt',
    [ValidateSet('brave', 'chrome', 'chromium', 'edge', 'firefox', 'opera', 'safari', 'vivaldi', 'whale')]
    [string] $Browser = 'firefox',
    [switch] $Preview                                    # list what would be downloaded, download nothing
)
$ErrorActionPreference = 'Stop'

# ---- 1. check the inputs and the tools ----
$gaveBothOrNeither = [bool]$Url -eq [bool]$ListFile          # true when both are given, or neither
if ($gaveBothOrNeither) { throw 'Give exactly one of -Url (creator page) or -ListFile (post URL list).' }

$haveYtDlp = Get-Command yt-dlp -ErrorAction SilentlyContinue
if (-not $haveYtDlp) { throw 'yt-dlp not found (winget install yt-dlp.yt-dlp).' }

# the creator becomes a folder name, so it can't hold characters Windows folders refuse
if ($Creator -match '[<>:"/\\|?*]') { throw "Creator folder name can't contain < > : "" / \ | ? *" }

# ---- 2. the inbox folder for this creator, and the folder for the archive file ----
$dest = Join-Path $Inbox $Creator
$archiveFolder = Split-Path $Archive
New-Item -ItemType Directory -Force -Path $dest, $archiveFolder | Out-Null

# ---- 3. the yt-dlp arguments ----
$ytArgs = @(
    '--cookies-from-browser', $Browser,
    '--download-archive', $Archive,
    '--ignore-errors', '--no-abort-on-error',          # text/image posts have no media: skip them
    '--windows-filenames', '--trim-filenames', '180',
    '-o', (Join-Path $dest '%(title)s [%(id)s].%(ext)s')
)

# optional filters
if ($Match) { $ytArgs += @('--match-filters', "title~='(?i)$Match'") }
if ($After) { $ytArgs += @('--dateafter', $After) }
if ($Preview) { $ytArgs += @('--simulate', '--print', '%(upload_date)s  %(title)s') }

# where the posts come from: a creator page, or a file of post URLs
if ($Url) { $ytArgs += $Url } else { $ytArgs += @('-a', $ListFile) }

# ---- 4. run it ----
$previewNote = if ($Preview) { '  (preview only)' }
Write-Host "yt-dlp -> $dest$previewNote"
& yt-dlp @ytArgs

# ---- 5. what to do next ----
Write-Host "`nNext: python reaction_rename.py --root ""\\nas\media\reaction"" --src ""$Inbox"" (dry run, then --apply; --new-shows for shows the library doesn't have yet)"
