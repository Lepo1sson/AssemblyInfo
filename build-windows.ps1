param(
    [string]$Python = "py",
    [string]$ExeName = "AssemblyInfo"
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

& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name $ExeName `
    $EntryPoint

Write-Host ""
Write-Host "Build termine: $(Join-Path $ProjectDir "dist\$ExeName.exe")"
