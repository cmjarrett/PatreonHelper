# Test for Sync-Reactions.ps1 in -Offline -ReportOnly mode: a throw-away library + saved listings, no network.
#   pwsh ./test_sync_reactions.ps1
$ErrorActionPreference = 'Stop'
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("sync-test-" + [guid]::NewGuid())
$root = Join-Path $tmp 'reaction'; $state = Join-Path $tmp 'state'
New-Item -ItemType Directory -Force -Path (Join-Path $root 'Creator A/Severance'), $state | Out-Null
Set-Content -Path (Join-Path $root 'Creator A/Severance/Severance - S01E01.mp4') -Value 'x'
$rows = @(
    "1`tFull Length | Severance | 1x1`thttps://www.patreon.com/posts/1",
    "2`tFull Length | Severance | 1x2`thttps://www.patreon.com/posts/2",
    "3`tFull Length | Game of Thrones | 1x1`thttps://www.patreon.com/posts/3",
    "4`tFull Length | One Piece | 100 & 101`thttps://www.patreon.com/posts/4"
)
Set-Content -Path (Join-Path $state 'creator-a.tsv') -Value $rows -Encoding utf8
@{
    _comment  = 'test'
    _defaults = @{ exclude = @('One Piece') }
    'Creator A' = @{ url = 'https://example.invalid'; handling = 'patreon'; include = @('Severance', 'Game of Thrones') }
    'Creator B' = @{ url = 'https://example.invalid'; handling = 'separate' }
} | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $tmp 'creators.json') -Encoding utf8

$fails = 0
function Check($name, $got, $want) {
    $ok = "$got" -eq "$want"
    if (-not $ok) { $script:fails++ }
    Write-Host ($(if ($ok) { 'ok  ' } else { 'FAIL' })) $name $(if (-not $ok) { "`n     got  $got`n     want $want" })
}

$env:PYTHONUTF8 = '1'
$log = & "$PSScriptRoot/Sync-Reactions.ps1" -Config (Join-Path $tmp 'creators.json') -Root $root -StateDir $state `
    -Archive (Join-Path $tmp 'downloaded.txt') -Offline -ReportOnly *>&1 | Out-String
$missing = @(Get-Content (Join-Path $state 'creator-a-missing.txt') | Where-Object { $_ }) -join ','
Check 'categories: Severance gap + Game of Thrones, One Piece excluded by _defaults' $missing 'https://www.patreon.com/posts/2,https://www.patreon.com/posts/3'
Check 'non-patreon creator skipped' ($log -match "Creator B : skipped") $true
Check 'owned post seeded into the archive' ((Get-Content (Join-Path $tmp 'downloaded.txt')) -join ',') 'patreon 1'

$null = & "$PSScriptRoot/Sync-Reactions.ps1" -Config (Join-Path $tmp 'creators.json') -Root $root -StateDir $state `
    -Archive (Join-Path $tmp 'downloaded.txt') -Offline -ReportOnly -Include 'Game of Thrones' *>&1
$missing = @(Get-Content (Join-Path $state 'creator-a-missing.txt') | Where-Object { $_ }) -join ','
Check '-Include replaces the file''s categories' $missing 'https://www.patreon.com/posts/3'

Remove-Item -Recurse -Force $tmp
Write-Host "`n$(if ($fails) { "$fails FAILED" } else { 'ALL PASSED' })"
exit [int]($fails -gt 0)
