# Test for Sync-Reactions.ps1: offline, a throw-away library, a stand-in downloader (no Patreon, no yt-dlp).
#   pwsh ./test_sync_reactions.ps1
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("sync-test-" + [guid]::NewGuid().ToString('N'))
$fails = 0
function Check([string] $name, $got, $want) {
    $ok = "$got" -eq "$want"
    if (-not $ok) { $script:fails++ }
    Write-Host ("{0} {1}{2}" -f $(if ($ok) { 'ok  ' } else { 'FAIL' }), $name, $(if ($ok) { '' } else { "`n     got  $got`n     want $want" }))
}

try {
    # ---- a library with one episode, a saved listing of three posts, one of them fetched before ----
    $root = Join-Path $tmp 'reaction'
    $show = Join-Path (Join-Path $root 'Creator A') 'Vinland Saga'
    $state = Join-Path $tmp 'state'
    $inbox = Join-Path $tmp 'inbox'
    New-Item -ItemType Directory -Force -Path $show, $state | Out-Null
    Set-Content -LiteralPath (Join-Path $show 'Vinland Saga - S01E01.mp4') -Value 'x'
    $tab = "`t"
    $posts = @(
        "501${tab}Vinland Saga | 1x1${tab}https://www.patreon.com/posts/501",
        "502${tab}Vinland Saga | 1x2${tab}https://www.patreon.com/posts/502",
        "503${tab}Vinland Saga | 1x3${tab}https://www.patreon.com/posts/503"
    )
    [IO.File]::WriteAllText((Join-Path $state 'creatora.tsv'), (($posts -join "`n") + "`n"))
    $config = Join-Path $tmp 'creators.json'
    Set-Content -LiteralPath $config -Value '{"Creator A": {"url": "https://www.patreon.com/a", "handling": "patreon"}}'
    $archive = Join-Path $tmp 'downloaded.txt'
    Set-Content -LiteralPath $archive -Value 'patreon 502'
    $never = Join-Path $tmp 'never-keep.txt'

    # the stand-in downloader writes down what it was asked to do
    $called = Join-Path $tmp 'called.txt'
    $stub = Join-Path $tmp 'Fake-Download.ps1'
    Set-Content -LiteralPath $stub -Value @"
param([string] `$Creator, [string] `$ListFile, [string] `$Inbox, [string] `$Archive, [string] `$Browser, [int] `$MaxDownloads, [switch] `$IgnoreRecord)
Add-Content -LiteralPath '$called' -Value ("{0}|{1}|{2}{3}" -f `$Creator, ((Get-Content `$ListFile) -join ','), `$MaxDownloads, `$(if (`$IgnoreRecord) { '|past the record' }))
"@
    $common = @{ Config = $config; Root = $root; Inbox = $inbox; Archive = $archive; NeverFile = $never
                 StateDir = $state; Offline = $true; Downloader = $stub }
    $sync = Join-Path $here 'Sync-Reactions.ps1'

    & $sync @common -ReportOnly *> $null
    Check 'report only: the downloader is not called' (Test-Path $called) $false

    & $sync @common -MaxDownloads 5 *> $null
    Check 'only the post that is neither in the library nor in the record is downloaded' (Get-Content $called) 'Creator A|https://www.patreon.com/posts/503|5'
    Check 'the owned post is written into the record' ((Get-Content $archive) -contains 'patreon 501') $true
    Check 'the lock is released' (Test-Path (Join-Path $state 'sync.lock')) $false
    Check 'a log is written' (@(Get-ChildItem (Join-Path $state 'logs') -Filter 'sync-*.log').Count -ge 1) $true
    Check 'nothing is filed into the library' (@(Get-ChildItem $root -Recurse -File).Count) 1

    # -RefetchMajorityHeld: the fetched-before episode of a show the library mostly holds is fetched again, past the record.
    # The library holds 1 of the show's 3 posts (33%), so 30 is "mostly" here and the default 65 is not.
    Remove-Item -LiteralPath $called
    & $sync @common -RefetchMajorityHeld *> $null
    Check 'refetch: a show held 33% is left alone at the default 65' (Get-Content $called) 'Creator A|https://www.patreon.com/posts/503|0'
    Remove-Item -LiteralPath $called
    & $sync @common -RefetchMajorityHeld -HeldPercent 30 *> $null
    Check 'refetch: the new post, then the fetched-before one past the record' ((Get-Content $called) -join ' ; ') 'Creator A|https://www.patreon.com/posts/503|0 ; Creator A|https://www.patreon.com/posts/502|0|past the record'
    Remove-Item -LiteralPath $called
    & $sync @common -RefetchMajorityHeld -HeldPercent 30 -ReportOnly *> $null
    Check 'refetch with report only: the downloader is not called' (Test-Path $called) $false

    # a run that is still going holds the lock: the second one does nothing
    Set-Content -LiteralPath $called -Value 'x'
    Remove-Item -LiteralPath $called
    Set-Content -LiteralPath (Join-Path $state 'sync.lock') -Value $PID
    & $sync @common *> $null
    Check 'a second run while one is going does nothing' (Test-Path $called) $false
    Remove-Item -LiteralPath (Join-Path $state 'sync.lock')

    # the library is not reachable: stop before anything is listed
    $threw = $false
    try { & $sync @common -Root (Join-Path $tmp 'not-mounted') *> $null } catch { $threw = $true }
    Check 'unreachable library: the run stops' $threw $true
    Check 'unreachable library: nothing downloaded' (Test-Path $called) $false
}
finally {
    Remove-Item -Recurse -Force -LiteralPath $tmp -ErrorAction SilentlyContinue
}
Write-Host ("`n" + $(if ($fails) { "$fails FAILED" } else { 'ALL PASSED' }))
exit $fails
