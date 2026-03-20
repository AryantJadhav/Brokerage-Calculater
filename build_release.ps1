Param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"

Write-Host "[1/4] Building app with PyInstaller (onedir)..."
$iconPath = "assets\app_logo.ico"
$iconArg = @()
if (Test-Path $iconPath) {
    Write-Host "Using app icon: $iconPath"
    $iconArg = @("--icon", $iconPath)
} else {
    Write-Host "Icon not found at assets\app_logo.ico. Building without EXE icon (runtime icon still uses assets\app_logo.png)."
}

$pythonExe = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at venv\Scripts\python.exe. Activate/create the venv first."
}

& $pythonExe -m PyInstaller --noconfirm --clean --windowed --onedir --name BrokerageCalculator --collect-all customtkinter @iconArg main.py

Write-Host "[2/4] Checking Inno Setup compiler..."
$isccCmd = Get-Command iscc -ErrorAction SilentlyContinue
$iscc = $null
if ($isccCmd) {
    $iscc = $isccCmd.Source
}
if (-not $iscc) {
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\InnoSetup6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            $iscc = $candidate
            break
        }
    }
}
if (-not $iscc) {
    throw "Inno Setup compiler 'ISCC.exe' not found. Install Inno Setup 6."
}

Write-Host "[3/4] Building installer..."
& $iscc /DMyAppVersion=$Version installer.iss

Write-Host "[4/4] Done. Installer output is in dist_installer/."
