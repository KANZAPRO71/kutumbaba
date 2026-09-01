# Script to auto-setup ADB, build, and install Persona AI APK to connected Android device
param(
    [string]$DeviceSerial = ""
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Persona AI - Android APK Build & Install " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Check and Auto-Download ADB if missing
$adb = $null
$adbCmd = Get-Command adb -ErrorAction SilentlyContinue
if ($adbCmd) {
    $adb = "adb"
} else {
    $sdkLocations = @(
        "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
        "$env:LOCALAPPDATA\Android\platform-tools\adb.exe",
        "$env:ANDROID_HOME\platform-tools\adb.exe",
        "$env:ANDROID_SDK_ROOT\platform-tools\adb.exe",
        "C:\platform-tools\adb.exe"
    )
    foreach ($loc in $sdkLocations) {
        if (Test-Path $loc) {
            $adb = $loc
            break
        }
    }
}

if (-not $adb) {
    Write-Host "[INFO] ADB tidak ditemukan di sistem. Mengunduh Google Platform-Tools (ADB resmi)..." -ForegroundColor Yellow
    $ptDir = "$env:LOCALAPPDATA\Android\platform-tools"
    $ptZip = "$env:TEMP\platform-tools-windows.zip"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-Host "  -> Mengunduh dari Google repository..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri "https://dl.google.com/android/repository/platform-tools-latest-windows.zip" -OutFile $ptZip -UseBasicParsing
        Write-Host "  -> Mengekstrak ke $ptDir..." -ForegroundColor Cyan
        $extractParent = Split-Path -Parent $ptDir
        if (-not (Test-Path $extractParent)) { New-Item -ItemType Directory -Path $extractParent -Force | Out-Null }
        Expand-Archive -Path $ptZip -DestinationPath $extractParent -Force
        $adb = "$ptDir\adb.exe"
        if (Test-Path $adb) {
            Write-Host "  -> ADB berhasil disiapkan!" -ForegroundColor Green
            # Add to current session PATH
            $env:PATH = "$ptDir;$env:PATH"
        }
    } catch {
        Write-Host "[ERROR] Gagal mengunduh ADB otomatis: $_" -ForegroundColor Red
        exit 1
    }
}

Write-Host "[1/5] Memeriksa koneksi perangkat Android..." -ForegroundColor Yellow
$devicesOutput = & $adb devices
$devices = @()
$lines = $devicesOutput -split "`r?`n"
for ($i = 1; $i -lt $lines.Count; $i++) {
    $line = $lines[$i].Trim()
    if ($line -and -not $line.StartsWith("*")) {
        $parts = $line -split "\s+"
        if ($parts.Count -ge 2 -and $parts[1] -eq "device") {
            $devices += $parts[0]
        } elseif ($parts.Count -ge 2 -and $parts[1] -eq "unauthorized") {
            Write-Host "[WARNING] Perangkat $($parts[0]) belum di-otorisasi." -ForegroundColor Red
            Write-Host "Silakan lihat layar HP Anda, lalu centang 'Selalu izinkan dari komputer ini' dan tekan 'Izinkan' (OK)." -ForegroundColor Yellow
        }
    }
}

if ($devices.Count -eq 0) {
    Write-Host "[ERROR] Tidak ada perangkat Android terdeteksi via ADB." -ForegroundColor Red
    Write-Host "Langkah aktivasi di HP Vivo V2318:" -ForegroundColor Yellow
    Write-Host " 1. Buka Pengaturan -> Tentang Ponsel -> Info Perangkat Lunak -> Ketuk 'Nomor Versi / Build Number' 7 kali sampai muncul 'Anda sekarang adalah pengembang'."
    Write-Host " 2. Buka Pengaturan -> Sistem -> Opsi Pengembang (Developer Options) -> Aktifkan 'Debugging USB'."
    Write-Host " 3. Pasang ulang kabel USB ke PC dan pilih 'Transfer File' di HP."
    Write-Host " 4. Saat muncul dialog 'Izinkan Debugging USB?' di layar HP, klik 'Izinkan' / 'OK'."
    exit 1
}

$targetDevice = if ($DeviceSerial) { $DeviceSerial } else { $devices[0] }
Write-Host "  -> Terhubung ke perangkat: $targetDevice" -ForegroundColor Green

$projectRoot = Split-Path -Parent $PSScriptRoot

# HP pakai backend lokal — tidak perlu start_server.bat atau adb reverse
Write-Host "[2/5] Backend di HP (embedded Python) — PC server tidak diperlukan." -ForegroundColor Green

$androidDir = Join-Path $projectRoot "android"
Set-Location $androidDir

Write-Host "[3/5] Memeriksa environment Java / Gradle..." -ForegroundColor Yellow

$javaCmd = Get-Command java -ErrorAction SilentlyContinue
if (-not $javaCmd) {
    # Check default Java/JDK paths in Program Files
    $javaPaths = @(
        "$env:JAVA_HOME\bin\java.exe",
        "C:\Program Files\Android\Android Studio\jbr\bin\java.exe",
        "C:\Program Files\Android\Android Studio\jre\bin\java.exe",
        "C:\Program Files\Java\*\bin\java.exe",
        "C:\Program Files\Eclipse Adoptium\*\bin\java.exe"
    )
    foreach ($pattern in $javaPaths) {
        $found = Get-Item $pattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            $javaBin = Split-Path -Parent $found.FullName
            $env:PATH = "$javaBin;$env:PATH"
            $env:JAVA_HOME = Split-Path -Parent $javaBin
            break
        }
    }
}

$apkPath = Join-Path $androidDir "app\build\outputs\apk\debug\app-debug.apk"

# Check if Gradle Wrapper is available
$gradlew = Join-Path $androidDir "gradlew.bat"
if (Test-Path $gradlew) {
    Write-Host "  -> Menjalankan build APK via Gradle wrapper (backend embedded)..." -ForegroundColor Cyan
    & $gradlew assembleDebug
} else {
    $gradleCmd = Get-Command gradle -ErrorAction SilentlyContinue
    if ($gradleCmd) {
        Write-Host "  -> Menjalankan gradle assembleDebug..." -ForegroundColor Cyan
        & gradle assembleDebug
    } else {
        Write-Host "[INFO] Android Gradle wrapper belum terinisialisasi." -ForegroundColor Yellow
        Write-Host "Anda dapat meng-compile APK dengan membuka folder '$androidDir' di Android Studio lalu klik 'Build -> Build APK(s)'." -ForegroundColor Cyan
    }
}

if (-not (Test-Path $apkPath)) {
    $altApk = Get-ChildItem -Path "$androidDir\app\build\outputs\apk" -Filter "*.apk" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($altApk) {
        $apkPath = $altApk.FullName
    }
}

if (-not (Test-Path $apkPath)) {
    Write-Host "[INFO] File APK belum ter-build." -ForegroundColor Yellow
    Write-Host "Untuk meng-compile APK:" -ForegroundColor Cyan
    Write-Host " Buka folder 'android' di Android Studio -> Klik 'Build' -> 'Build APK(s)'." -ForegroundColor Cyan
    Write-Host "Setelah itu jalankan script ini kembali." -ForegroundColor Cyan
    exit 0
}

Write-Host "  -> APK berhasil ditemukan: $apkPath" -ForegroundColor Green

# 4. Install APK
Write-Host "[4/5] Menginstall APK ke perangkat ($targetDevice)..." -ForegroundColor Yellow
& $adb -s $targetDevice install -r $apkPath
Write-Host "  -> APK berhasil terinstall!" -ForegroundColor Green

# 5. Launch App (debug build uses applicationIdSuffix ".debug")
Write-Host "[5/5] Menjalankan aplikasi Persona AI di HP..." -ForegroundColor Yellow
$launchPkg = "com.persona.ai.debug"
& $adb -s $targetDevice shell am start -n "$launchPkg/com.persona.ai.MainActivity"
Write-Host "==========================================" -ForegroundColor Green
Write-Host " Sukses! Persona AI berjalan di HP Anda. " -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
