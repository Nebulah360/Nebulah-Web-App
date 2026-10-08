# JRPC2 module operations. Only the Python plugin adapter may request these actions.
$script:modulePhase = $null
$script:moduleStatus = $null
$script:modulePathMode = $null
function Get-ModuleNames($Console) {
  $inventory = Get-ConsoleModuleInventory $Console
  if ($inventory.state -ne 'observed') { throw 'Module inventory unavailable' }
  return @($inventory.modules | ForEach-Object { [string]$_.name })
}

function Wait-ModuleCount($Console, [string]$Name, [int]$Expected, [int]$Attempts=5) {
  for ($attempt=0; $attempt -lt $Attempts; $attempt++) {
    if (@(Get-ModuleNames $Console | Where-Object { $_ -ieq $Name }).Count -eq $Expected) { return $true }
    if ($attempt -lt $Attempts-1) { Start-Sleep -Milliseconds 250 }
  }
  return $false
}

function Invoke-JrpcReply($Console, [string]$Command) {
  $channel = $Console.OpenConnection($null)
  try {
    $reply = Read-TelemetryReply $Console $channel $Command
    for ($attempt=0; $attempt -lt 12 -and $reply -match '^buf_addr=(?:0x)?([0-9A-Fa-f]{1,8})$'; $attempt++) {
      $address = $Matches[1]
      Start-Sleep -Milliseconds 250
      $reply = Read-TelemetryReply $Console $channel ('consolefeatures buf_addr=0x' + $address)
    }
    if ($reply -match '^buf_addr=') { throw 'JRPC2 call did not finish' }
    return $reply
  }
  finally { if ($null -ne $channel) { try { [void]$Console.CloseConnection($channel) } catch {} } }
}

function Resolve-JrpcExport($Console, [string]$Module, [int]$Ordinal) {
  $bytes = [Text.Encoding]::ASCII.GetBytes($Module)
  $hex = [BitConverter]::ToString($bytes).Replace('-','')
  $command = 'consolefeatures ver=2 type=9 params="A\0\A\2\2/' + $bytes.Length + '\' + $hex + '\1\' + $Ordinal + '\"'
  $reply = Invoke-JrpcReply $Console $command
  if ($reply -notmatch '^(?:0x)?[0-9A-Fa-f]{1,8}$') { throw 'JRPC2 export resolution failed' }
  $address = [Convert]::ToUInt32(($reply -replace '^0x',''),16)
  if ($address -eq 0) { throw 'JRPC2 export unavailable' }
  return $address
}

function Invoke-JrpcInt32($Console, [uint32]$Address, [object[]]$Arguments) {
  $parts = @()
  foreach ($argument in $Arguments) {
    if ($argument -is [string]) {
      $bytes = [Text.Encoding]::ASCII.GetBytes($argument)
      if ($bytes.Length -gt 512 -or [Text.Encoding]::ASCII.GetString($bytes) -cne $argument) { throw 'JRPC2 path must be ASCII' }
      $parts += '7/' + $bytes.Length + '\' + [BitConverter]::ToString($bytes).Replace('-','') + '\'
    } elseif ($argument -is [int] -or $argument -is [uint32]) {
      $signed = [BitConverter]::ToInt32([BitConverter]::GetBytes([uint32]$argument), 0)
      $parts += '1\' + [string]$signed + '\'
    } else { throw 'Unsupported JRPC2 argument' }
  }
  $command = 'consolefeatures ver=2 type=1 system as=0 params="A\' + $Address.ToString('X') + '\A\' + $parts.Count + '\' + ($parts -join '') + '"'
  $reply = Invoke-JrpcReply $Console $command
  if ($reply -notmatch '^(?:0x)?[0-9A-Fa-f]{1,8}$') { throw 'JRPC2 call returned an invalid status' }
  return [Convert]::ToUInt32(($reply -replace '^0x',''),16)
}

function Test-JrpcModuleRuntime($Console) {
  $names = Get-ModuleNames $Console
  if (-not ($names | Where-Object { $_ -ieq 'JRPC2.xex' })) { throw 'JRPC2 module unavailable' }
  [void](Resolve-JrpcExport $Console 'xboxkrnl.exe' 409)
  [void](Resolve-JrpcExport $Console 'xboxkrnl.exe' 417)
  [void](Resolve-JrpcExport $Console 'xam.xex' 1102)
  return $true
}

function Get-NebulahComponentName($Console) {
  $names = @(Get-ModuleNames $Console | Where-Object { $_ -imatch '^NebulahCompanion(?:-[A-Za-z0-9_]+)?\.xex$' })
  if ($names.Count -ne 1) { throw 'Nebulah companion XEX is not loaded' }
  $name = $names[0]
  $entry = Resolve-JrpcExport $Console $name 1
  $script:nebulahProtocol = Invoke-JrpcInt32 $Console $entry @()
  if ($script:nebulahProtocol -notin @(0x4E424C02,0x4E424C03,0x4E424C04)) { throw 'Nebulah companion protocol is incompatible' }
  return $name
}

function Invoke-NebulahFunction($Console, [string]$Name, [int]$Ordinal, [object[]]$Arguments) {
  $entry = Resolve-JrpcExport $Console $Name $Ordinal
  return Invoke-JrpcInt32 $Console $entry $Arguments
}

function Send-ConsoleNotification($Console, [string]$Message) {
  if ($Message -cnotmatch '^[\x20-\x7E]{1,80}$') { throw 'Invalid notification text' }
  if (-not (Get-ModuleNames $Console | Where-Object { $_ -ieq 'JRPC2.xex' })) { throw 'JRPC2 module unavailable' }
  $bytes = [Text.Encoding]::ASCII.GetBytes($Message)
  $hex = [BitConverter]::ToString($bytes).Replace('-','')
  $command = 'consolefeatures ver=2 type=12 params="A\0\A\2\7/' + $bytes.Length + '\' + $hex + '\1\34\"'
  [void](Invoke-JrpcReply $Console $command)
  return @{accepted=$true}
}

function Assert-PluginPath([string]$Path) {
  if ($Path.Length -lt 7 -or $Path.Length -gt 512 -or
      $Path -notmatch '^[A-Za-z0-9_]+:\\[^"<>|?*:/\x00-\x1f]+\.xex$' -or
      $Path -match '(?:^|\\)\.\.?\\') { throw 'Invalid module path' }
}

function Resolve-ModuleLoadPath($Console, [string]$Path, [string]$ExpectedSha256, [long]$ExpectedSize) {
  if ($ExpectedSha256 -cnotmatch '^[0-9a-f]{64}$' -or $ExpectedSize -lt 24 -or $ExpectedSize -gt 67108864) {
    throw 'Measured module identity unavailable'
  }
  $file = $Console.GetFileObject($Path)
  if ($file.IsDirectory -or $file.Size -ne $ExpectedSize) { throw 'Module file changed; inspect it again' }
  # Neighborhood exposes Usb0:, while console-side loaders commonly use Usb:.
  # Never infer that the roots are equivalent: compare the candidate's full bytes.
  if ($Path -notmatch '^Usb0:\\') { return $Path }
  $alias = 'Usb:' + $Path.Substring(5)
  try {
    $candidate = $Console.GetFileObject($alias)
    if ($candidate.IsDirectory -or $candidate.Size -ne $ExpectedSize) { return $Path }
    $temp = [IO.Path]::GetTempFileName()
    try {
      $Console.ReceiveFile($temp, $alias)
      if ((Get-Item -LiteralPath $temp).Length -ne $ExpectedSize) { return $Path }
      $digest = (Get-FileHash -LiteralPath $temp -Algorithm SHA256).Hash.ToLowerInvariant()
      if ($digest -ceq $ExpectedSha256) {
        $script:modulePathMode = 'verified-usb-alias'
        return $alias
      }
    } finally { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
  } catch {
    # The selected path remains eligible; an unavailable alias must not become
    # a different unverified load target.
  }
  return $Path
}

function Invoke-ModuleLoad($Console, [string]$Path, [string]$ExpectedSha256, [long]$ExpectedSize) {
  $script:modulePhase = 'module-path'
  $script:moduleStatus = $null
  $script:modulePathMode = 'selected-path'
  Assert-PluginPath $Path
  $script:modulePhase = 'module-probe'
  [void](Test-JrpcModuleRuntime $Console)
  $name = ($Path -split '\\')[-1]
  if (@(Get-ModuleNames $Console | Where-Object { $_ -ieq $name }).Count -ne 0) { throw 'Module already loaded' }
  $script:modulePhase = 'module-file'
  $runtimePath = Resolve-ModuleLoadPath $Console $Path $ExpectedSha256 $ExpectedSize
  $script:modulePhase = 'module-resolve'
  $entry = Resolve-JrpcExport $Console 'xboxkrnl.exe' 409
  $script:modulePhase = 'module-call'
  $status = Invoke-JrpcInt32 $Console $entry @($runtimePath,8,0,0)
  $script:modulePhase = 'module-result'
  $script:moduleStatus = '0x' + $status.ToString('X8')
  if ($status -ne 0) { throw 'Module load failed' }
  $script:modulePhase = 'module-inventory'
  if (-not (Wait-ModuleCount $Console $name 1)) { throw 'Module load was not observed' }
  return @{ok=$true; name=$name; state='loaded'; runtime_path=$runtimePath; path_mode=$script:modulePathMode}
}

function Invoke-ModuleUnload($Console, [string]$Name) {
  $script:modulePhase = 'module-path'
  $script:moduleStatus = $null
  $script:modulePathMode = $null
  if ($Name -notmatch '^[A-Za-z0-9_.-]{1,128}\.xex$') { throw 'Invalid module name' }
  $script:modulePhase = 'module-probe'
  [void](Test-JrpcModuleRuntime $Console)
  $script:modulePhase = 'module-inventory'
  if (@(Get-ModuleNames $Console | Where-Object { $_ -ieq $Name }).Count -ne 1) { throw 'Module is not loaded' }
  $script:modulePhase = 'module-handle'
  $handleEntry = Resolve-JrpcExport $Console 'xam.xex' 1102
  $handle = Invoke-JrpcInt32 $Console $handleEntry @($Name)
  if ($handle -eq 0) { throw 'Module handle unavailable' }
  $script:modulePhase = 'module-resolve'
  $unloadEntry = Resolve-JrpcExport $Console 'xboxkrnl.exe' 417
  $script:modulePhase = 'module-call'
  $status = Invoke-JrpcInt32 $Console $unloadEntry @([uint32]$handle)
  $script:modulePhase = 'module-result'
  $script:moduleStatus = '0x' + $status.ToString('X8')
  if ($status -ne 0) { throw 'Module unload failed' }
  $script:modulePhase = 'module-inventory'
  if (-not (Wait-ModuleCount $Console $Name 0 20)) { throw 'Module remains loaded' }
  return @{ok=$true; name=$Name; state='unloaded'}
}
