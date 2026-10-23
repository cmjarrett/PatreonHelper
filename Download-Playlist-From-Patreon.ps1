<#
.SYNOPSIS
  Download every post listed in a text file of Patreon post URLs (one per line) with yt-dlp.
  The list usually comes from Clean-Patreon-PlayList-HTML.ps1. Download-Creator.ps1 does the same with more options.

.EXAMPLE
  .\Download-Playlist-From-Patreon.ps1 -FileName C:\patreon\show_clean.txt -Browser firefox
#>
param(
    # text file with one post URL per line
    [String]
    $FileName,

    # the browser whose Patreon login yt-dlp borrows
    [Parameter(Mandatory=$true)]
    [ValidateSet("brave","chrome","chromium","edge","firefox","opera","safari","vivaldi","whale")]
    $Browser
)

# yt-dlp reads the URLs from the file (-a) and uses the browser's cookies for the login
yt-dlp.exe --cookies-from-browser $Browser -a $FileName