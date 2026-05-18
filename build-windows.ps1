param(
    [string]$Python = "python",
    [string]$ExeName = "AssemblyInfo",
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir ".venv-windows"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$EntryPoint = Join-Path $ProjectDir "assembly_info_gui.py"
$Requirements = Join-Path $ProjectDir "requirements-windows.txt"

Set-Location $ProjectDir

if (-not (Test-Path $PythonExe)) {
    & $Python -m venv $VenvDir
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r $Requirements

$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $ExeName
)

if ($OneFile) {
    $PyInstallerArgs += "--onefile"
}

$PyInstallerArgs += $EntryPoint
& $PythonExe -m PyInstaller @PyInstallerArgs

Write-Host ""
if ($OneFile) {
    Write-Host "Build termine: $(Join-Path $ProjectDir "dist\$ExeName.exe")"
} else {
    Write-Host "Build termine: $(Join-Path $ProjectDir "dist\$ExeName\$ExeName.exe")"
    Write-Host "Mode onedir utilise pour accelerer le lancement Windows."
}
