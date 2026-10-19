<#
.SYNOPSIS
  Keep the reaction library in sync with the creators you follow: for each creator, list the posts (only new ones
  after the first run), find what the library is missing, download it, and optionally import it.

.DESCRIPTION
  Reads a creators file (JSON, see reaction-creators.example.json) and runs, per creator:
    1. reaction_gaps.py   list posts (saved per creator in -StateDir, so later runs only read new posts),
                          compare with the library, write <creator>-missing.txt
    2. Download-Creator.ps1   download the missing posts into -Inbox\<Creator>
  and, with -Import, reaction_rename.py over the inbox at the end (dry run; add -Apply to move the files).

  Download categories: you don't have to mirror everything a creator posts. Give each creator an "include" list
  in the creators file (or -Include on the command line) and only posts whose title, or show, matches one of the
  terms are downloaded: "Game of Thrones" matches every post with Game of Thrones in the title (case, spaces and
  punctuation ignored), and via the aliases file "Fullmetal Alchemist" also matches "FMAB episode 3". An "exclude"
  list (or -Exclude) removes shows or movies you never want; it wins over include. A top-level "_defaults" entry
  applies to every creator. Changing the categories later needs no new listing: run with -Offline to re-check
  the saved listings in seconds.

.EXAMPLE
  .\Sync-Reactions.ps1 -Config ..\private\reaction-creators.json -Root "\\nas\media\reaction" -ReportOnly
  .\Sync-Reactions.ps1 -Config ..\private\reaction-creators.json -Root "\\nas\media\reaction" -Creator "Creator A"
  .\Sync-Reactions.ps1 -Config ..\private\reaction-creators.json -Root "\\nas\media\reaction" -Include "Game of Thrones","Severance" -Offline -ReportOnly
  .\Sync-Reactions.ps1 -Config ..\private\reaction-creators.json -Root "\\nas\media\reaction" -Import            # then -Import -Apply
#>
param(
    [Parameter(Mandatory = $true)] [string] $Config,    # creators JSON (keep yours outside this public repo)
    [Parameter(Mandatory = $true)] [string] $Root,      # library root, e.g. \\nas\media\reaction
    [string] $Aliases,                                  # show-name aliases JSON for reaction_gaps / reaction_rename
    [string[]] $Creator,                                # only these creators (default: all with handling "patreon")
    [string[]] $Include,                                # download categories for this run (replaces the file's)
    [string[]] $Exclude,                                # never these (added to the file's)
    [string] $Inbox = 'C:\patreon\inbox',
    [string] $Archive = 'C:\patreon\downloaded.txt',
    [string] $StateDir = (Join-Path $PSScriptRoot 'sync-state'),
    [ValidateSet('brave', 'chrome', 'chromium', 'edge', 'firefox', 'opera', 'safari', 'vivaldi', 'whale')]
    [string] $Browser = 'firefox',
    [switch] $ReportOnly,                               # list and compare, download nothing
    [switch] $Offline,                                  # use the saved listings only (no Patreon requests)
    [switch] $Import,                                   # after the downloads: reaction_rename.py over the inbox
    [switch] $Apply                                     # with -Import: really move the files (default dry run)
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'python not found on PATH.' }
$cfg = Get-Content -Raw -Encoding UTF8 $Config | ConvertFrom-Json
$defaults = $cfg.PSObject.Properties['_defaults'].Value
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Get-List($obj, $name) {                        # a JSON array property as a string array (missing -> empty)
    if ($null -eq $obj) { return @() }
    $p = $obj.PSObject.Properties[$name]
    if ($null -eq $p -or $null -eq $p.Value) { return @() }
    return @($p.Value | ForEach-Object { [string]$_ })
}
function Get-Flag($obj, $name, $default) {
    if ($null -ne $obj -and $null -ne $obj.PSObject.Properties[$name]) { return [bool]$obj.$name }
    return $default
}

$summary = @()
foreach ($prop in $cfg.PSObject.Properties) {
    $name, $c = $prop.Name, $prop.Value
    if ($name.StartsWith('_')) { continue }                                   # _comment, _defaults
    if ($Creator -and $Creator -notcontains $name) { continue }
    $handling = if ($c.PSObject.Properties['handling']) { $c.handling } else { 'patreon' }
    $url = if ($c.PSObject.Properties['url']) { $c.url } else { $null }
    $listFile = if ($c.PSObject.Properties['list_file']) { $c.list_file } else { $null }
    if ($handling -ne 'patreon') { Write-Host "-- $name : skipped (handling '$handling')"; continue }
    $slug = ($name -replace '[^\w]+', '-').Trim('-').ToLower()
    $tsv = Join-Path $StateDir "$slug.tsv"
    if ($Offline -and -not (Test-Path $tsv)) { Write-Host "-- $name : skipped (no saved listing yet)"; continue }
    if (-not $Offline -and -not $url -and -not $listFile) { Write-Host "-- $name : skipped (no url / list_file)"; continue }

    $inc = if ($Include) { @($Include) } else { @(Get-List $c 'include') + @(Get-List $defaults 'include') }
    $exc = @(Get-List $c 'exclude') + @(Get-List $defaults 'exclude') + @($Exclude | Where-Object { $_ })
    $out = Join-Path $StateDir $slug
    $gapArgs = @((Join-Path $here 'reaction_gaps.py'), '--root', $Root, '--creator', $name, '--out', $out,
                 '--seed-archive', $Archive, '--browser', $Browser)
    if ($Offline) { $gapArgs += @('--from-tsv', $tsv) }
    elseif ($url) { $gapArgs += @('--url', $url, '--save-tsv', $tsv) }
    else { $gapArgs += @('--list-file', $listFile, '--save-tsv', $tsv) }
    if ($Aliases) { $gapArgs += @('--aliases', $Aliases) }
    if (Get-Flag $c 'new_shows' (Get-Flag $defaults 'new_shows' $true)) { $gapArgs += '--include-new' }
    if (Get-Flag $c 'movies' (Get-Flag $defaults 'movies' $true)) { $gapArgs += '--include-movies' }
    foreach ($t in $inc) { $gapArgs += @('--only', $t) }
    foreach ($t in $exc) { $gapArgs += @('--skip', $t) }

    Write-Host "`n== $name$(if ($inc) { "  (only: $($inc -join ', '))" })$(if ($exc) { "  (never: $($exc -join ', '))" })"
    & python @gapArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "$name : the listing/report failed (exit $LASTEXITCODE); the next run resumes from $tsv"
        $summary += [pscustomobject]@{ Creator = $name; Missing = '?'; Downloaded = 'no (listing failed)' }
        continue
    }
    $missingFile = "$out-missing.txt"
    $missing = @(Get-Content $missingFile -ErrorAction SilentlyContinue | Where-Object { $_.Trim() }).Count
    $done = 'no'
    if ($missing -gt 0 -and -not $ReportOnly) {
        & (Join-Path $here 'Download-Creator.ps1') -Creator $name -ListFile $missingFile -Inbox $Inbox -Archive $Archive -Browser $Browser
        $done = 'yes'
    }
    elseif ($missing -eq 0) { $done = '-' }
    $summary += [pscustomobject]@{ Creator = $name; Missing = $missing; Downloaded = $done }
}

Write-Host "`n== Summary"
$summary | Format-Table -AutoSize | Out-String | Write-Host
if ($Import) {
    $renArgs = @((Join-Path $here 'reaction_rename.py'), '--root', $Root, '--src', $Inbox, '--new-shows')
    if ($Aliases) { $renArgs += @('--aliases', $Aliases) }
    if ($Apply) { $renArgs += '--apply' }
    Write-Host "== Import$(if (-not $Apply) { ' (dry run: add -Apply to move the files)' })"
    & python @renArgs
}
