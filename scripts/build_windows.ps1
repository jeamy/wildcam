param(
  [string]$PythonExe = "py",
  [string]$AppName = "wildcam",
  [string]$EntryPoint = "main.py",
  [string]$ArtifactSuffix = ""
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
  --onedir `
  --windowed `
  --name $AppName `
  --add-data "assets/icons;assets/icons" `
  --collect-all "PyQt6" `
  --collect-all "cv2" `
  --collect-all "numpy" `
  $EntryPoint

$bundlePath = Join-Path $distDir $AppName
if (!(Test-Path $bundlePath)) {
  throw "Build failed: bundle not found at $bundlePath"
}

$extraFiles = @(
  "README.md",
  "docker-compose.yml",
  "neolink_manager.py",
  "camera_config.json.example"
)

foreach ($extraFile in $extraFiles) {
  if (Test-Path $extraFile) {
    Copy-Item $extraFile -Destination $bundlePath -Force
  }
}

if (Test-Path "neolink.toml") {
  Copy-Item "neolink.toml" -Destination $bundlePath -Force
}

if ([string]::IsNullOrWhiteSpace($ArtifactSuffix)) {
  $ArtifactSuffix = Get-Date -Format "yyyyMMdd_HHmmss"
}

$zipName = ("{0}_windows_{1}.zip" -f $AppName, $ArtifactSuffix)
$zipPath = Join-Path $distDir $zipName

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $bundlePath -DestinationPath $zipPath

Write-Host "BUNDLE: $bundlePath"
Write-Host "ZIP: $zipPath"
