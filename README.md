# PatreonHelper
Helper for Patreon users


This tool is intended to help mostly non-technical users make copies of patreon videos, in particular 'collections' of videos.
There is one-time manual work of going to the Patreon Collection url and retrieving one inner Node from the Browser Inspector.


As a user you need to:
 * Download the two scripts and place them in your working directory (C:\patreon for this example)
 * Login to Patreon using your browser of choice ( the scripts are configured for FireFox)
 * Go to the Collection you wish to download (https://www.patreon.com/collection/11111111111111?view=expanded)
 * Make Sure EVERY video you want to download is present on the page.  For Large Collections you will often have to hit 'expand' to load the entire collection.
 * Press Ctrl+Shift+I to go to the 'Browser Inspector'
 * Right Click the top-level node and copy->Inner HTML
 * Paste in your desired temp file.  I do somethign like 'C:\patreon\deathnote_blahcreator.txt'
 * open up a powershell window in your working directory (C:\patreon)
 * >.\Clean-Patreon-PlayList-HTML.ps1 -FileName:C:\patreon\deathnote_blahcreator.txt
       This will spit out a clean list of URLs.  Paste that into another file for the next portion (e.g. C:\patreon\deathnote_clean.txt)
 * >.\Download-Playlist-From-Patreon.ps1 -playlist C:\patreon\\deathnote_clean.txt
       This downloads using YT-DLP the entire collection at best video preference.