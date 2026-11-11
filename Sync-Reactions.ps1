<#
.SYNOPSIS
  One unattended run for every creator you follow: find the new posts, download them into the inbox, stop.
  Made to run on a schedule (Install-SyncTask.ps1). It never files anything into the library.

.DESCRIPTION
  1. reaction_gaps_all.py lists every creator's posts (Patreon's public API) and compares them with the library,
     the download record and the never-keep list. A post is downloaded only when all three say so:
       - the library does not hold it,
       - the download record (-Archive, yt-dlp's archive file) does not hold its id: a post fetched once is never
         fetched again, also when you deleted the file from the library afterwards,
       - its show is not on the never-keep list (-NeverFile, or "exclude" in the creators file).
     Posts the library holds are written into the download record on every run.
  2. Download-Creator.ps1 downloads what is left into -Inbox\<Creator>\ . That is the staging folder.
  3. Nothing else. Look through the inbox yourself, then file what you keep with reaction_rename.py and delete
     the rest; deleted posts stay in the download record, so they do not come back.

  Each run writes a log to -StateDir\logs and holds a lock file, so a second run that starts while a long
  download is still going ends at once. If the library is not reachable the run stops before listing anything
  (otherwise every post would look missing).

.EXAMPLE
  .\Sync-Reactions.ps1 -Config C:\private\reaction-creators.json -Root "\\nas\media\reaction" -ReportOnly
  .\Sync-Reactions.ps1 -Config C:\private\reaction-creators.json -Root "\\nas\media\reaction" -Aliases C:\private\reaction-aliases.json
  .\Sync-Reactions.ps1 -Config C:\private\reaction-creators.json -Root "\\nas\media\reaction" -Creator "Creator A" -MaxDownloads 20
#>
param(
    [Parameter(Mandatory = $true)] [string] $Config,    # creators JSON (keep yours outside this public repo)
    [Parameter(Mandatory = $true)] [string] $Root,      # library root, e.g. \\nas\media\reaction (only read)
    [string] $Aliases,                                  # show-name aliases JSON
    [string] $Creator,                                  # only this creator (default: all in the creators file)
    [string] $Inbox = 'C:\patreon\inbox',               # staging: downloads land here and stay here
    [string] $Archive = 'C:\patreon\downloaded.txt',    # the download record
    [string] $NeverFile = 'C:\patreon\never-keep.txt',  # the never-keep list
    [string] $StateDir = 'C:\patreon\sync',             # listings, download lists, logs, lock
    [ValidateSet('brave', 'chrome', 'chromium', 'edge', 'firefox', 'opera', 'safari', 'vivaldi', 'whale')]
    [string] $Browser = 'firefox',
    [int] $MaxDownloads = 0,                            # per creator and run (0 = no limit)
    [switch] $ReportOnly,                               # list and compare, download nothing
    [switch] $Offline,                                  # use the saved listings (no Patreon request)
    [string] $Downloader = (Join-Path $PSScriptRoot 'Download-Creator.ps1')   # for the tests
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'                                   # post titles hold characters the console code page lacks

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'python not found on PATH.' }
if (-not (Test-Path -LiteralPath $Config)) { throw "creators file not found: $Config" }
if (-not (Test-Path -LiteralPath $Root)) { throw "library root not reachable: $Root (nothing listed, nothing downloaded)" }

# ---- 1. log and lock ----
$logDir = Join-Path $StateDir 'logs'
New-Item -ItemType Directory -Force -Path $StateDir, $logDir | Out-Null
$log = Join-Path $logDir ("sync-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
function Say([string] $text) {
    Write-Host $text
    Add-Content -LiteralPath $log -Value $text -Encoding utf8
}

$lock = Join-Path $StateDir 'sync.lock'
if (Test-Path -LiteralPath $lock) {
    $otherPid = (Get-Content -LiteralPath $lock -TotalCount 1) -as [int]
    if ($otherPid -and (Get-Process -Id $otherPid -ErrorAction SilentlyContinue)) {
        Say "another run is still going (process $otherPid): nothing done"
        exit 0
    }
    Say "stale lock from process $otherPid removed"
}
Set-Content -LiteralPath $lock -Value $PID

try {
    Say "== sync started $(Get-Date -Format 'yyyy-MM-dd HH:mm')  inbox: $Inbox  record: $Archive"

    # ---- 2. what is new: one gap list per creator ----
    $gapArgs = @((Join-Path $PSScriptRoot 'reaction_gaps_all.py'), '--creators', $Config, '--root', $Root,
                 '--out-dir', $StateDir, '--archive', $Archive, '--never-file', $NeverFile)
    if ($Aliases) { $gapArgs += @('--aliases', $Aliases) }
    if ($Creator) { $gapArgs += @('--creator', $Creator) }
    if ($Offline) { $gapArgs += '--offline' }

    $plan = Join-Path $StateDir 'sync-plan.json'
    Remove-Item -LiteralPath $plan -ErrorAction SilentlyContinue      # never act on an earlier run's plan

    $ErrorActionPreference = 'Continue'                 # python writes progress to stderr: not an error
    & python @gapArgs 2>&1 | ForEach-Object { Say "$_" }
    $gapExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if (-not (Test-Path -LiteralPath $plan)) { throw "the listing failed (exit $gapExit): no plan written, nothing downloaded" }

    # ---- 3. download into the inbox, creator by creator ----
    $todo = @(Get-Content -Raw -LiteralPath $plan -Encoding utf8 | ConvertFrom-Json)
    $summary = @()
    foreach ($item in $todo) {
        $state = 'nothing new'
        if ($item.count -gt 0 -and $ReportOnly) { $state = 'report only' }
        elseif ($item.count -gt 0) {
            Say "`n== $($item.creator): $($item.count) posts to download"
            $dlArgs = @{ Creator = $item.creator; ListFile = $item.list; Inbox = $Inbox; Archive = $Archive; Browser = $Browser }
            if ($MaxDownloads -gt 0) { $dlArgs.MaxDownloads = $MaxDownloads }
            try {
                $ErrorActionPreference = 'Continue'     # yt-dlp reports posts it can't open on stderr and goes on
                & $Downloader @dlArgs *>&1 | ForEach-Object { Say "$_" }
                $state = 'download run'
            }
            catch {
                Say "!! $($item.creator): $_"
                $state = 'failed'
            }
            finally { $ErrorActionPreference = 'Stop' }
        }
        $summary += [pscustomobject]@{ Creator = $item.creator; ToDownload = $item.count; Result = $state }
    }

    # ---- 4. summary ----
    Say "`n== Summary"
    ($summary | Format-Table -AutoSize | Out-String).Trim() -split "`r?`n" | ForEach-Object { Say $_ }
    Say "`nDownloads are in $Inbox and stay there. File what you keep with reaction_rename.py; delete the rest."
    Say "log: $log"
}
finally {
    Remove-Item -LiteralPath $lock -ErrorAction SilentlyContinue
}
