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

pyinstaller --noconfirm --clean --windowed --onedir --name BrokerageCalculator --collect-all customtkinter @iconArg main.py

Write-Host "[2/4] Checking Inno Setup compiler..."
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
    throw "Inno Setup compiler 'iscc' not found in PATH. Install Inno Setup 6 and add ISCC.exe to PATH."
}

Write-Host "[3/4] Building installer..."
iscc /DMyAppVersion=$Version installer.iss

Write-Host "[4/4] Done. Installer output is in dist_installer/."
