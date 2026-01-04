param(
  [string]$PythonExe = "py",
  [string]$AppName = "wildcam",
  [string]$EntryPoint = "main.py"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (!(Test-Path $EntryPoint)) {
  throw "Entry point not found: $EntryPoint"
}

$venvDir = Join-Path $repoRoot ".venv"
$distDir = Join-Path $repoRoot "dist"
$buildDir = Join-Path $repoRoot "build"

if (!(Test-Path $venvDir)) {
  & $PythonExe -m venv $venvDir
}

$python = Join-Path $venvDir "Scripts\python.exe"
$pip = Join-Path $venvDir "Scripts\pip.exe"

& $python -m pip install --upgrade pip

if (Test-Path "requirements.txt") {
  & $pip install -r "requirements.txt"
}

& $pip install "pyinstaller>=6.0"

if (Test-Path $distDir) { Remove-Item $distDir -Recurse -Force }
if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }

& $python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name $AppName `
  $EntryPoint

$exePath = Join-Path $distDir ("{0}.exe" -f $AppName)
if (!(Test-Path $exePath)) {
  throw "Build failed: EXE not found at $exePath"
}

$zipName = ("{0}_windows_{1}.zip" -f $AppName, (Get-Date -Format "yyyyMMdd_HHmmss"))
$zipPath = Join-Path $distDir $zipName

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $exePath -DestinationPath $zipPath

Write-Host "EXE: $exePath"
Write-Host "ZIP: $zipPath"
