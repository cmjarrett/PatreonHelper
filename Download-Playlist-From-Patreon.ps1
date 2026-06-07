param(

    [String]
    $FileName,
	[Parameter(Mandatory=$true)]
	[ValidateSet("brave","chrome","chromium","edge","firefox","opera","safari","vivaldi","whale")]
	$Browser
)

yt-dlp.exe --cookies-from-browser $Browser -a $FileName