param(
    [string]$ExePath = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([string]::IsNullOrWhiteSpace($ExePath)) {
    $OneDirExe = Join-Path $ProjectDir "dist\AssemblyInfo\AssemblyInfo.exe"
    $OneFileExe = Join-Path $ProjectDir "dist\AssemblyInfo.exe"
    if (Test-Path $OneDirExe) {
        $ExePath = $OneDirExe
    } else {
        $ExePath = $OneFileExe
    }
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
