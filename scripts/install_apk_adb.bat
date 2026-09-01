@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo  Persona AI - Android APK Build ^& Install
echo ==========================================

REM 1. Check ADB and Auto-Download if missing
set "ADB_EXE="
where adb >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "ADB_EXE=adb"
) else (
    if exist "%LOCALAPPDATA%\Android\platform-tools\adb.exe" (
        set "ADB_EXE=%LOCALAPPDATA%\Android\platform-tools\adb.exe"
    ) else if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" (
        set "ADB_EXE=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
    )
)

if not defined ADB_EXE (
    echo [INFO] ADB tidak ditemukan di sistem. Mengunduh Google Platform-Tools (ADB)...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile '%TEMP%\platform-tools.zip' -UseBasicParsing; Expand-Archive -Path '%TEMP%\platform-tools.zip' -DestinationPath '%LOCALAPPDATA%\Android' -Force"
    if exist "%LOCALAPPDATA%\Android\platform-tools\adb.exe" (
        set "ADB_EXE=%LOCALAPPDATA%\Android\platform-tools\adb.exe"
        echo   -^> ADB berhasil diunduh dan dipasang!
    ) else (
        echo [ERROR] Gagal memasang ADB otomatis.
        pause
        exit /b 1
    )
)

echo [1/4] Memeriksa koneksi perangkat HP...
"%ADB_EXE%" devices
echo.

echo [2/4] Mengatur port forwarding ADB (tcp:8765 -> tcp:8765)...
"%ADB_EXE%" reverse tcp:8765 tcp:8765
if %ERRORLEVEL% equ 0 (
    echo   -^> Port 8765 berhasil di-reverse!
) else (
    echo   -^> [WARNING] Gagal reverse port. Pastikan USB Debugging diizinkan di HP.
)
echo.

echo [3/4] Memeriksa file APK...
set "APK_PATH=%~dp0..\android\app\build\outputs\apk\debug\app-debug.apk"
if not exist "%APK_PATH%" (
    for /r "%~dp0..\android\app\build\outputs\apk" %%f in (*.apk) do set "APK_PATH=%%f"
)

if not exist "%APK_PATH%" (
    cd /d "%~dp0..\android"
    if exist "gradlew.bat" (
        call gradlew.bat assembleDebug
    ) else (
        where gradle >nul 2>nul
        if !ERRORLEVEL! equ 0 (
            call gradle assembleDebug
        )
    )
)

if not exist "%APK_PATH%" (
    for /r "%~dp0..\android\app\build\outputs\apk" %%f in (*.apk) do set "APK_PATH=%%f"
)

if not exist "%APK_PATH%" (
    echo [INFO] File APK belum ter-build.
    echo Buka project 'android' di Android Studio lalu klik Build -^> Build APK.
    pause
    exit /b 0
)

echo [4/4] Menginstall dan membuka APK di HP...
"%ADB_EXE%" install -r "%APK_PATH%"
"%ADB_EXE%" shell am start -n com.persona.ai.debug/com.persona.ai.MainActivity

echo.
echo ==========================================
echo  Selesai! Aplikasi Persona AI aktif di HP.
echo ==========================================
pause
