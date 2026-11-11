<#
.SYNOPSIS
  Register (or remove) a Windows scheduled task that runs Sync-Reactions.ps1 every N days.

.DESCRIPTION
  The task runs as you, only while you are logged on: the download needs your browser's Patreon login and your
  access to the library share, and both belong to your logon session. No password is stored.
  A run that is still downloading when the next one is due is not started twice (the task ignores the new start,
  and Sync-Reactions.ps1 holds a lock as well). A run missed because the PC was off starts at the next logon.

  -Preview prints the task's command line and schedule and registers nothing.
  -Remove unregisters the task. The download record, the inbox and the logs are not touched.

.EXAMPLE
  .\Install-SyncTask.ps1 -Config C:\private\reaction-creators.json -Root "\\nas\media\reaction" -Preview
  .\Install-SyncTask.ps1 -Config C:\private\reaction-creators.json -Root "\\nas\media\reaction" -Aliases C:\private\reaction-aliases.json -At 03:30 -DaysInterval 1 -MaxDownloads 40
  .\Install-SyncTask.ps1 -Remove
#>
[CmdletBinding(DefaultParameterSetName = 'Install')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Install')] [string] $Config,
    [Parameter(Mandatory = $true, ParameterSetName = 'Install')] [string] $Root,
    [Parameter(ParameterSetName = 'Install')] [string] $Aliases,
    [Parameter(ParameterSetName = 'Install')] [string] $At = '03:30',          # start time, 24-hour HH:mm
    [Parameter(ParameterSetName = 'Install')] [int] $DaysInterval = 1,          # every N days
    [Parameter(ParameterSetName = 'Install')] [int] $MaxDownloads = 0,          # per creator and run (0 = no limit)
    [Parameter(ParameterSetName = 'Install')] [string] $Inbox,
    [Parameter(ParameterSetName = 'Install')] [string] $Archive,
    [Parameter(ParameterSetName = 'Install')] [string] $NeverFile,
    [Parameter(ParameterSetName = 'Install')] [string] $StateDir,
    [Parameter(ParameterSetName = 'Install')] [switch] $Preview,
    [Parameter(Mandatory = $true, ParameterSetName = 'Remove')] [switch] $Remove,
    [string] $TaskName = 'PatreonHelper Sync'
)
$ErrorActionPreference = 'Stop'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "task '$TaskName' removed (download record, inbox and logs untouched)"
    return
}

# ---- 1. the command the task runs ----
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh.exe' } else { 'powershell.exe' }
$script = Join-Path $PSScriptRoot 'Sync-Reactions.ps1'
function Quote([string] $value) { '"' + $value + '"' }

$arguments = @('-NoProfile', '-WindowStyle', 'Hidden', '-File', (Quote $script), '-Config', (Quote $Config), '-Root', (Quote $Root))
if ($Aliases) { $arguments += @('-Aliases', (Quote $Aliases)) }
if ($Inbox) { $arguments += @('-Inbox', (Quote $Inbox)) }
if ($Archive) { $arguments += @('-Archive', (Quote $Archive)) }
if ($NeverFile) { $arguments += @('-NeverFile', (Quote $NeverFile)) }
if ($StateDir) { $arguments += @('-StateDir', (Quote $StateDir)) }
if ($MaxDownloads -gt 0) { $arguments += @('-MaxDownloads', "$MaxDownloads") }
$argumentLine = $arguments -join ' '

$startTime = [datetime]::ParseExact($At, 'HH:mm', [cultureinfo]::InvariantCulture)
Write-Host "task:     $TaskName"
Write-Host "runs:     every $DaysInterval day(s) at $At, as $env:USERNAME, only while logged on"
Write-Host "command:  $shell $argumentLine"
if ($Preview) { Write-Host '(preview: nothing registered)'; return }

# ---- 2. register it ----
$action = New-ScheduledTaskAction -Execute $shell -Argument $argumentLine -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -DaysInterval $DaysInterval -At $startTime
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 20) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "registered. Run it once now with:  Start-ScheduledTask -TaskName '$TaskName'"
