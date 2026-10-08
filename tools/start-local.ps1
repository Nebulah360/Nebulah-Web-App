param([Parameter(ValueFromRemainingArguments=$true)][string[]]$BridgeArguments)
$ErrorActionPreference = 'Stop'
$Project = Split-Path $PSScriptRoot -Parent
$failureCode = 'STARTUP_FAILED'

function Find-NebulahPython {
  $candidates = New-Object 'System.Collections.Generic.List[object]'
  foreach ($name in @('py.exe','python.exe')) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch '\\WindowsApps\\python.exe$') {
      $prefix = @(); if ($name -eq 'py.exe') { $prefix = @('-3') }
      $candidates.Add(@{Exe=$command.Source; Prefix=$prefix})
    }
  }
  foreach ($root in @('HKCU:\Software\Python\PythonCore','HKLM:\Software\Python\PythonCore','HKLM:\Software\WOW6432Node\Python\PythonCore')) {
    if (Test-Path $root) {
      foreach ($version in Get-ChildItem $root) {
        $key = Get-Item ($version.PSPath + '\InstallPath') -ErrorAction SilentlyContinue
        if ($key) {
          $exe = $key.GetValue('ExecutablePath')
          if (-not $exe) { $exe = Join-Path ($key.GetValue('')) 'python.exe' }
          if ($exe -and (Test-Path -LiteralPath $exe)) { $candidates.Add(@{Exe=$exe; Prefix=@()}) }
        }
      }
    }
  }
  foreach ($candidate in $candidates) {
    $prefix = $candidate.Prefix
    try {
      $result = & $candidate.Exe @prefix -c 'import sys,sqlite3; print(sys.executable if sys.version_info >= (3,10) else str())' 2>$null
      if ($LASTEXITCODE -eq 0 -and $result -and (Test-Path -LiteralPath ([string]$result))) { return [string]$result }
    } catch { }
  }
  return $null
}

function Test-NeighborhoodRegistration([string]$Executable) {
  if (-not (Test-Path -LiteralPath $Executable)) { return $false }
  & $Executable -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check-neighborhood.ps1') 2>$null | Out-Null
  return $LASTEXITCODE -eq 0
}

try {
  Set-Location -LiteralPath $Project
  if ($BridgeArguments -contains '--allow-phone') {
    $firewallArguments = @($BridgeArguments | Where-Object { $_ -ne '--allow-phone' })
    & (Join-Path $PSScriptRoot 'allow-phone.ps1') @firewallArguments
    exit $LASTEXITCODE
  }
  $settingsPath = Join-Path $Project '.local\launcher-settings.json'
  if (-not (Test-Path -LiteralPath $settingsPath)) {
    New-Item -ItemType Directory -Path (Split-Path $settingsPath) -Force | Out-Null
    [IO.File]::WriteAllText($settingsPath, '{"schema":1,"phone_access":true,"browser":"default","open_browser":true}' + [Environment]::NewLine, (New-Object Text.UTF8Encoding $false))
    Write-Host 'First-run launcher settings saved. Change them under Console > Launcher settings.'
  }
  $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
  $names = @($settings.PSObject.Properties.Name)
  if ($names.Count -ne 4 -or @($names | Where-Object { $_ -notin @('schema','phone_access','browser','open_browser') }).Count -gt 0 -or
      $settings.schema -isnot [int] -or $settings.schema -ne 1 -or $settings.phone_access -isnot [bool] -or
      $settings.open_browser -isnot [bool] -or $settings.browser -notin @('default','chrome')) {
    throw 'Launcher settings are invalid. Fix or remove .local\launcher-settings.json, then start again.'
  }
  $phoneMode = $settings.phone_access
  $openBrowser = $settings.open_browser
  $browserChoice = $settings.browser
  $requestedArguments = @()
  for ($i=0; $i -lt $BridgeArguments.Count; $i++) {
    $argument = $BridgeArguments[$i]
    if ($argument -eq '--phone') { $phoneMode = $true }
    elseif ($argument -eq '--local-only') { $phoneMode = $false }
    elseif ($argument -eq '--no-open-browser') { $openBrowser = $false }
    elseif ($argument -eq '--browser') {
      if (++$i -ge $BridgeArguments.Count -or $BridgeArguments[$i] -notin @('default','chrome')) { throw '--browser requires default or chrome.' }
      $browserChoice = $BridgeArguments[$i]
    } else { $requestedArguments += $argument }
  }
  $BridgeArguments = @($requestedArguments) + @('--browser', $browserChoice)
  if ($phoneMode -and $BridgeArguments -notcontains '--host') {
    $failureCode = 'PHONE_SETUP_FAILED'
    $phoneAddress = & (Join-Path $PSScriptRoot 'phone-host.ps1')
    if ($phoneAddress -notmatch '^\d+\.\d+\.\d+\.\d+$') {
      throw "Phone address discovery failed. Run & '.\Start Nebulah Link.cmd' --host <your private PC IPv4> after checking ipconfig."
    }
    $BridgeArguments += @('--host', [string]$phoneAddress)
    Write-Host "Phone access selected: $phoneAddress"
    Write-Host 'Connect your phone to the same trusted network. Open the URL below and enter the six-digit Phone PIN shown in the PC browser.'
    Write-Host 'If the page will not open, allow this TCP port on the Windows Private profile for LocalSubnet only (see README Phone access).'
    $failureCode = 'STARTUP_FAILED'
  }
  Write-Host 'Nebulah Link - checking local requirements...'
  $standaloneExe = $env:NEBULAH_STANDALONE_EXE
  if ($standaloneExe) {
    if ($standaloneExe -ne (Join-Path $Project 'Nebulah-Link.exe') -or
        -not (Test-Path -LiteralPath $standaloneExe -PathType Leaf)) {
      throw 'Standalone launcher path does not match this extracted folder.'
    }
    $python = $standaloneExe
  } else { $python = Find-NebulahPython }
  if (-not $python) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) { $failureCode='PYTHON_MISSING'; throw 'Python 3.10+ is missing and WinGet is unavailable. Install Python from https://www.python.org/downloads/windows/ then double-click Start Nebulah Link.cmd again.' }
    $failureCode='PYTHON_INSTALL_FAILED'
    Write-Host 'Installing Python 3.13 for your Windows user through WinGet...'
    & $winget.Source install --id Python.Python.3.13 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Python installation did not complete. Check the WinGet message above; retry Start Nebulah Link.cmd after resolving it.' }
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
    $python = Find-NebulahPython
    if (-not $python) { $failureCode='PYTHON_RESTART_REQUIRED'; throw 'Python was installed but is not available in this window. Close it and double-click Start Nebulah Link.cmd again.' }
  }
  $failureCode='STARTUP_FAILED'
  if ($standaloneExe) { Write-Host 'Bundled Python ready; no separate Python installation required.' }
  else { Write-Host "Python ready: $python" }
  # Honor a requested COM architecture instead of silently changing it.
  $explicit = -1
  for ($i=0; $i -lt $BridgeArguments.Count; $i++) { if ($BridgeArguments[$i] -eq '--powershell') { $explicit=$i; break } }
  $chosen = $null
  if ($explicit -ge 0) {
    if ($explicit+1 -ge $BridgeArguments.Count) { throw '--powershell requires an executable path.' }
    $requested = $BridgeArguments[$explicit+1]
    if (Test-NeighborhoodRegistration $requested) { $chosen=$requested }
  } else {
    foreach ($candidate in @("$env:WINDIR\SysWOW64\WindowsPowerShell\v1.0\powershell.exe", "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe")) {
      if (Test-NeighborhoodRegistration $candidate) { $chosen=$candidate; break }
    }
  }
  if (-not $chosen) { $failureCode='NEIGHBORHOOD_MISSING'; throw 'Xbox 360 Neighborhood/XDevkit COM is unavailable. Install or repair your licensed Neighborhood installation, then retry. Nebulah does not download SDK binaries. No console was contacted.' }
  Write-Host 'Neighborhood registration ready. No pip/npm packages required.'
  if (-not $openBrowser) { Write-Host 'Browser opening is off. Open the printed URL on this PC to pair; keep this window open.' }
  elseif ($phoneMode) { Write-Host 'Your PC browser will pair automatically. Use Show Phone PIN in that browser, then enter the PIN on your phone. Keep this window open.' }
  else { Write-Host 'Your browser will open and pair automatically. Keep this window open.' }
  $launch = @()
  if ($standaloneExe) { $launch += '--bridge-child' }
  else { $launch += (Join-Path $Project 'bridge\server.py') }
  if ($openBrowser) { $launch += '--open-browser' }
  if ($explicit -lt 0) { $launch += @('--powershell',$chosen) }
  $restarts = 0
  while ($true) {
    $started = Get-Date
    & $python @launch @BridgeArguments
    $bridgeExit = $LASTEXITCODE
    Write-Host "Bridge process exited. Code: $bridgeExit"
    # Clean Ctrl+C and startup conflicts are intentional; never relaunch them.
    if ($bridgeExit -eq 0 -or $bridgeExit -eq 17 -or $bridgeExit -eq 18) { exit $bridgeExit }
    if (((Get-Date) - $started).TotalSeconds -ge 60) { $restarts = 0 }
    if ($restarts -ge 2) { exit $bridgeExit }
    $restarts++
    Write-Host "Unexpected bridge exit. Restarting in 3 seconds ($restarts of 2 consecutive failures)."
    Start-Sleep -Seconds 3
  }
} catch {
  if ($failureCode -eq 'PHONE_SETUP_FAILED') {
    Write-Host ('Phone setup stopped: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
  }
  try {
    $catalog = Get-Content (Join-Path $Project 'support\errors.json') -Raw | ConvertFrom-Json
    $help = $catalog.errors.$failureCode
    if (-not $help.support_code -or -not $help.message -or -not $help.next_step) { throw 'Incomplete support catalog' }
    Write-Host ('Stopped: ' + $help.message) -ForegroundColor Red
    Write-Host ('Next: ' + $help.next_step)
    Write-Host ('Support code: ' + $help.support_code)
  } catch { Write-Host 'Startup stopped. Run from a fully extracted project folder. Support code: NB-B05' -ForegroundColor Red }
  exit 1
}
