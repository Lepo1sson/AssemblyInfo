param(
    [string]$ExePath = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([string]::IsNullOrWhiteSpace($ExePath)) {
    $ExePath = Join-Path $ProjectDir "dist\AssemblyInfo.exe"
}

$ResolvedExe = Resolve-Path $ExePath
$SendToDir = [Environment]::GetFolderPath("SendTo")
$ShortcutPath = Join-Path $SendToDir "Assembly info.lnk"

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ResolvedExe.Path
$Shortcut.WorkingDirectory = Split-Path -Parent $ResolvedExe.Path
$Shortcut.Description = "Lire les infos Assembly d'un fichier .NET"
$Shortcut.Save()

Write-Host "Raccourci cree: $ShortcutPath"
Write-Host "Utilisation: clic droit sur un fichier -> Envoyer vers -> Assembly info"
