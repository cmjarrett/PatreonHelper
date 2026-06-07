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
