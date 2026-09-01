# Publish Papua AI APK to GitHub Releases (KANZAPRO71/kutumbaba)
# Prerequisite: gh auth login (once)
# Usage: .\scripts\publish_github_release.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

$Gradle = Join-Path $Root "android\app\build.gradle"
if (-not (Test-Path $Gradle)) {
    throw "build.gradle not found at $Gradle"
}

$versionName = (Select-String -Path $Gradle -Pattern 'versionName\s+"([^"]+)"').Matches[0].Groups[1].Value
$tag = "v$versionName"
$dist = Join-Path $Root "dist"
$apkSrc = Join-Path $Root "android\app\build\outputs\apk\debug\app-debug.apk"

Write-Host "Building APK..."
Push-Location (Join-Path $Root "android")
& .\gradlew assembleDebug | Out-Host
Pop-Location

if (-not (Test-Path $apkSrc)) {
    throw "APK not found: $apkSrc"
}

New-Item -ItemType Directory -Force -Path $dist | Out-Null
Copy-Item $apkSrc (Join-Path $dist "papua-ai-latest.apk") -Force
Copy-Item $apkSrc (Join-Path $dist "papua-ai-$versionName.apk") -Force

$gh = "C:\Program Files\GitHub CLI\gh.exe"
if (-not (Test-Path $gh)) {
    $gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
}
if (-not $gh) {
    throw "GitHub CLI (gh) not found. Install: winget install GitHub.cli"
}

& $gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Run once: gh auth login"
}

$notes = @"
## Papua AI Beta — $versionName

### Install
1. Download **papua-ai-latest.apk**
2. Install → buka Papua AI → Gemini API key → ngobrol

### Highlights
- FOLLOW_THROUGH: ikuti energi user santai/short tanpa dorong pertanyaan
- ConversationController sidecar (anti menu/interview/repeat)
- Fix tombol UI, voice picker, empty-turn silence
"@

$existing = & $gh release view $tag --repo KANZAPRO71/kutumbaba 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Updating release $tag ..."
    & $gh release upload $tag `
        (Join-Path $dist "papua-ai-latest.apk") `
        (Join-Path $dist "papua-ai-$versionName.apk") `
        --repo KANZAPRO71/kutumbaba --clobber
} else {
    Write-Host "Creating release $tag ..."
    & $gh release create $tag `
        --repo KANZAPRO71/kutumbaba `
        --title $tag `
        --notes $notes `
        (Join-Path $dist "papua-ai-latest.apk") `
        (Join-Path $dist "papua-ai-$versionName.apk")
}

Write-Host "Done: https://github.com/KANZAPRO71/kutumbaba/releases/tag/$tag"
