#Requires -RunAsAdministrator
$ErrorActionPreference = 'Continue'
Write-Host "=== Persona Bluetooth Repair ===" -ForegroundColor Cyan

# 1. USB selective suspend off
Write-Host "[1/7] Disable USB selective suspend..."
powercfg /SETACVALUEINDEX SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0 | Out-Null
powercfg /SETDCVALUEINDEX SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0 | Out-Null
powercfg /SETACTIVE SCHEME_CURRENT | Out-Null

# 2. Stop Bluetooth stack
Write-Host "[2/7] Restart Bluetooth services..."
@('bthserv', 'BTAGService', 'BthAvctpSvc') | ForEach-Object {
    Stop-Service $_ -Force -ErrorAction SilentlyContinue
    Set-Service $_ -StartupType Manual -ErrorAction SilentlyContinue
}

# 3. Remove broken + phantom Bluetooth/USB entries
Write-Host "[3/7] Remove broken and phantom devices..."
$toRemove = Get-PnpDevice | Where-Object {
    $_.InstanceId -match '8087.*0AAA|VID_0000&PID_0002\\5&237FFA2&0&14|BTH\\MS_|BTHENUM|SWD\\RADIO\\BLUETOOTH'
    -or ($_.FriendlyName -match 'Intel\(R\) Wireless Bluetooth|Microsoft Bluetooth' -and $_.Problem -eq 'CM_PROB_PHANTOM')
}
foreach ($dev in $toRemove) {
    Write-Host "  Remove: $($dev.FriendlyName) [$($dev.InstanceId)]"
    pnputil /remove-device $dev.InstanceId 2>&1 | Out-Null
    Remove-PnpDevice -InstanceId $dev.InstanceId -Confirm:$false -ErrorAction SilentlyContinue
}

# 4. Reset combo Wi-Fi chip (shared with Bluetooth)
Write-Host "[4/7] Reset Intel Wireless-AC 9560 combo chip..."
$wifi = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object {
    $_.FriendlyName -eq 'Intel(R) Wireless-AC 9560 160MHz'
}
if ($wifi) {
    Disable-PnpDevice -InstanceId $wifi.InstanceId -Confirm:$false -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 10
    Enable-PnpDevice -InstanceId $wifi.InstanceId -Confirm:$false -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 8
}

# 5. Reset USB 3 host controller
Write-Host "[5/7] Reset USB host controller..."
$xhc = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object {
    $_.FriendlyName -match 'USB 3.*Host Controller'
} | Select-Object -First 1
if ($xhc) {
    Disable-PnpDevice -InstanceId $xhc.InstanceId -Confirm:$false -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5
    Enable-PnpDevice -InstanceId $xhc.InstanceId -Confirm:$false -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 8
}

# 6. Rescan + force latest Intel BT driver package
Write-Host "[6/7] Rescan hardware..."
pnputil /scan-devices 2>&1 | Out-Null
Start-Sleep -Seconds 5

$btDev = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object {
    $_.InstanceId -match '8087.*0AAA'
}
if ($btDev) {
    Write-Host "  Bluetooth USB detected — updating driver..."
    pnputil /update-driver $btDev.InstanceId oem64.inf 2>&1
}

# 7. Start services
Write-Host "[7/7] Start Bluetooth services..."
Start-Service bthserv -ErrorAction SilentlyContinue
Start-Service BTAGService -ErrorAction SilentlyContinue
Start-Service BthAvctpSvc -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== RESULT ===" -ForegroundColor Cyan
Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object {
    $_.FriendlyName -match 'Bluetooth|8087|0AAA|Unknown USB'
} | Format-Table Status, Problem, FriendlyName -AutoSize

$btOk = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object {
    $_.FriendlyName -eq 'Intel(R) Wireless Bluetooth(R)' -and $_.Status -eq 'OK'
}
if ($btOk) {
    Write-Host "SUCCESS: Intel Bluetooth adapter OK" -ForegroundColor Green
} else {
    Write-Host "Bluetooth still not OK — full SHUTDOWN (not restart) required, then test again." -ForegroundColor Yellow
    Write-Host "If still fails after shutdown: BIOS wireless toggle or USB BT dongle." -ForegroundColor Yellow
}

Write-Host "Press Enter to close..."
Read-Host | Out-Null
