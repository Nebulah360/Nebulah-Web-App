# Run with the Windows PowerShell architecture matching installed XDevkit COM.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$manager = $null; $nativeConsole = $null; $console = $null; $connection = $null
$stage = 'com'; $failureCode = 'XDEVKIT_COM_FAILED'
$architecture = if ([IntPtr]::Size -eq 8) { 'x64' } else { 'x86' }
. "$PSScriptRoot/telemetry.ps1"
. "$PSScriptRoot/module_runtime.ps1"
. "$PSScriptRoot/launch_ini.ps1"

try {
  try { $manager = New-Object -ComObject 'XDevkit.XboxManager' } catch {
    # Some installations expose the registered COM class without this ProgID.
    # Activate only the XboxManager class; no SDK binaries are bundled/loaded.
    $managerType = [Type]::GetTypeFromCLSID([Guid]'A5EB45D8-F3B6-49B9-984A-0D313AB60342')
    $manager = [Activator]::CreateInstance($managerType)
  }
  $target = [string]$request.target
  if ([string]::IsNullOrWhiteSpace($target)) {
    $stage = 'default-console'; $failureCode = 'DEFAULT_CONSOLE_FAILED'
    $target = [string]$manager.DefaultConsole
    if ([string]::IsNullOrWhiteSpace($target)) {
      $failureCode = 'DEFAULT_CONSOLE_EMPTY'
      throw 'Default console unavailable'
    }
  }
  $stage = 'open-console'; $failureCode = 'CONSOLE_OPEN_FAILED'
  $nativeConsole = $manager.OpenConsole($target)
  if ($null -eq $nativeConsole) { throw 'Console object unavailable' }
  $stage = 'interface'; $failureCode = 'XDEVKIT_INTERFACE_FAILED'
  Add-Type -Path "$PSScriptRoot/ComDispatch.cs"
  $console = New-Object Nebulah.ConsoleDispatch -ArgumentList $nativeConsole
  # Set supported timeouts before the first remote operation, including drives.
  try { $console.ConnectTimeout = 2000 } catch {}
  try { $console.ConversationTimeout = 2000 } catch {}
  if ($request.action -in @('upload-file','verify-upload','download-file','receive')) {
    $console.ConversationTimeout = 180000
  } elseif ($request.action -in @('plugin-load','plugin-unload','launch-ini-apply','launch-ini-read','launch-ini-save','launch-ini-resolve-plugin')) {
    # XEX attach/detach and DashLaunch reparse can outlive read-only telemetry.
    $console.ConversationTimeout = 15000
  }
  $stage = 'operation'; $failureCode = 'ADAPTER_OPERATION_FAILED'
  switch ($request.action) {
    'status' {
      # Deliberate allowlist. Never serialize a COM console/debug object.
      $stage = 'storage'; $failureCode = 'STORAGE_DISCOVERY_FAILED'
      $storage = Get-ConsoleStorage $console
      $stage = 'operation'; $failureCode = 'ADAPTER_OPERATION_FAILED'
      $telemetry = Get-ConsoleTelemetry $console
      $telemetry.resolved_target = $target
      $telemetry.drives = @($storage.drives)
      $telemetry.storage = @{source=$storage.source; state=$storage.state}
      $telemetry | ConvertTo-Json -Depth 5 -Compress
    }
    'cpu-key' {
      # Only invoked by the bridge after explicit, single-use consent.
      $console.ConnectTimeout = 2000
      $console.ConversationTimeout = 2000
      $connection = $console.OpenConnection('')
      $response = ''
      $console.SendTextCommand($connection, 'consolefeatures ver=2 type=10 params="A\0\A\0\"', [ref]$response)
      if ($response -notmatch '^200[- ]+\s*([0-9a-fA-F]{32})\s*$') { throw 'CPU key unavailable' }
      @{ cpu_key=$Matches[1].ToUpperInvariant() } | ConvertTo-Json -Compress
      $response = $null
    }
    'plugins' {
      # Module observation only; do not infer DLL/plugin identity from a name.
      Get-ConsoleModuleInventory $console | ConvertTo-Json -Depth 4 -Compress
    }
    'launch-ini-export' {
      $stage = 'module'; $failureCode = 'MODULE_RUNTIME_UNAVAILABLE'
      $address = Resolve-JrpcExport $console 'launch.xex' 1
      @{address=('0x' + $address.ToString('X8')); target=$target} | ConvertTo-Json -Compress
    }
    'launch-ini-hash' {
      $stage = 'storage'; $failureCode = 'STORAGE_BROWSE_FAILED'
      $path = [string]$request.path
      if ($path -notmatch '^[A-Za-z0-9_]+:\\launch\.ini$') { throw 'Expected a storage-root launch.ini' }
      $file = $console.GetDownloadFileInfo($path)
      if ($file.IsDirectory -or $file.Size -lt 1 -or $file.Size -gt 131072) { throw 'launch.ini outside read limits' }
      $temp = [IO.Path]::GetTempFileName()
      try {
        $console.ReceiveFile($temp, $path)
        if ((Get-Item -LiteralPath $temp).Length -ne $file.Size) { throw 'launch.ini changed during read' }
        @{sha256=(Get-FileHash -LiteralPath $temp -Algorithm SHA256).Hash.ToLowerInvariant(); size=[long]$file.Size} | ConvertTo-Json -Compress
      } finally { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
    }
    'launch-ini-read' {
      $stage = 'storage'; $failureCode = 'STORAGE_BROWSE_FAILED'
      Get-LaunchIniSnapshot $console ([string]$request.path) | ConvertTo-Json -Compress
    }
    'launch-ini-resolve-plugin' {
      $stage = 'module'; $failureCode = 'MODULE_RUNTIME_UNAVAILABLE'
      Assert-PluginPath ([string]$request.path)
      $runtime = Resolve-ModuleLoadPath $console ([string]$request.path) ([string]$request.sha256) ([long]$request.size)
      @{runtime_path=$runtime; path_mode=$script:modulePathMode} | ConvertTo-Json -Compress
    }
    'launch-ini-save' {
      $stage = 'launch-ini'; $failureCode = 'LAUNCH_INI_SAVE_FAILED'
      Save-LaunchIniFile $console ([string]$request.path) ([string]$request.expected_sha256) ([string]$request.new_sha256) ([string]$request.local) | ConvertTo-Json -Compress
    }
    'launch-ini-apply' {
      $stage = 'module'; $failureCode = 'ADAPTER_OPERATION_FAILED'
      $device = [string]$request.device_path
      if ($device -cnotin @('\Device\Mass0\','\Device\Mass1\','\Device\Mass2\','\Device\Harddisk0\Partition1\','\Device\BuiltInMuSfc\','\Device\BuiltInMuUsb\Storage\','\Device\BuiltInMuMmc\Storage\','\SystemRoot\')) {
        throw 'Unsupported DashLaunch device path'
      }
      $entry = Resolve-JrpcExport $console 'launch.xex' 4
      [void](Invoke-JrpcInt32 $console $entry @($device))
      @{requested=$true} | ConvertTo-Json -Compress
    }
    'plugin-probe' {
      $stage = 'module'; $failureCode = 'MODULE_RUNTIME_UNAVAILABLE'
      [void](Test-JrpcModuleRuntime $console)
      @{ready=$true; backend='jrpc2'} | ConvertTo-Json -Compress
    }
    'component-ping' {
      $stage = 'module'; $failureCode = 'MODULE_RUNTIME_UNAVAILABLE'
      $name = [string]$request.name
      if ($name -cnotmatch '^NebulahCompanion(?:-[A-Za-z0-9_]+)?\.xex$' -or
          @(Get-ModuleNames $console | Where-Object { $_ -ieq $name }).Count -ne 1) { throw 'Nebulah companion module unavailable' }
      $entry = Resolve-JrpcExport $console $name 1
      $value = Invoke-JrpcInt32 $console $entry @()
      @{protocol=$value} | ConvertTo-Json -Compress
    }
    'component-probe' {
      $stage = 'module'; $failureCode = 'MODULE_RUNTIME_UNAVAILABLE'
      $name = Get-NebulahComponentName $console
      @{ready=$true; name=$name; protocol=($script:nebulahProtocol -band 0xFF); capacity=32; force_release=($script:nebulahProtocol -in @(0x4E424C03,0x4E424C04))} | ConvertTo-Json -Compress
    }
    'component-input-probe' {
      $stage = 'module'; $failureCode = 'MODULE_RUNTIME_UNAVAILABLE'
      $name = Get-NebulahComponentName $console
      $state = if ($script:nebulahProtocol -eq 0x4E424C04) { Invoke-NebulahFunction $console $name 8 @() } else { 0 }
      if ($state -notin @(0,1,2)) { throw 'Nebulah input probe returned an invalid state' }
      @{available=($state -in @(1,2)); active=($state -eq 2)} | ConvertTo-Json -Compress
    }
    'component-input-pulse' {
      $stage = 'module'; $failureCode = 'ADAPTER_OPERATION_FAILED'
      $name = Get-NebulahComponentName $console
      if ($script:nebulahProtocol -ne 0x4E424C04) { throw 'Nebulah input protocol is unavailable' }
      $buttons = [int]$request.buttons
      if ($buttons -le 0 -or ($buttons -band (-bnot 0xF3FF)) -ne 0) { throw 'Invalid controller buttons' }
      if ((Invoke-NebulahFunction $console $name 8 @()) -notin @(1,2)) { throw 'Nebulah input hook is unavailable' }
      $script:modulePhase = 'module-result'
      $script:moduleStatus = '0x' + (Invoke-NebulahFunction $console $name 9 @($buttons)).ToString('X8')
      if ($script:moduleStatus -eq '0x0000B105') { throw 'Virtual controller binding was not confirmed' }
      if ($script:moduleStatus -eq '0x0000B104') { throw 'The running title did not read the input pulse' }
      if ($script:moduleStatus -notin @('0x00000000','0x00000001')) { throw 'Nebulah input pulse was rejected' }
      @{accepted=$true; mode=$(if ($script:moduleStatus -eq '0x00000001') { 'virtual' } else { 'connected-controller' })} | ConvertTo-Json -Compress
    }
    'component-load' {
      $stage = 'module'; $failureCode = 'MODULE_LOAD_FAILED'
      $script:modulePhase = 'module-path'; $script:modulePathMode = 'selected-path'; $script:moduleStatus = $null
      $name = Get-NebulahComponentName $console
      $path = [string]$request.path
      Assert-PluginPath $path
      $runtime = Resolve-ModuleLoadPath $console $path ([string]$request.sha256) ([long]$request.size)
      $script:modulePhase = 'module-result'
      $status = Invoke-NebulahFunction $console $name 4 @($runtime)
      $script:moduleStatus = '0x' + $status.ToString('X8')
      if ($status -ne 0) { throw 'Nebulah manager rejected module load' }
      $module = ($path -split '\\')[-1]
      $script:modulePhase = 'module-inventory'
      if (-not (Wait-ModuleCount $console $module 1)) { throw 'Managed module load was not observed' }
      @{ok=$true; name=$module; runtime_path=$runtime; path_mode=$script:modulePathMode; state='loaded'} | ConvertTo-Json -Compress
    }
    'component-state' {
      $stage = 'module'; $failureCode = 'MODULE_RUNTIME_UNAVAILABLE'
      $name = Get-NebulahComponentName $console
      $module = [string]$request.name
      if ($module -notmatch '^[\x20-\x7E]{1,124}\.xex$' -or $module -match '[\\/:*?"<>|]') { throw 'Invalid module name' }
      $value = Invoke-NebulahFunction $console $name 5 @($module)
      @{state=[int]$value} | ConvertTo-Json -Compress
    }
    'component-unload' {
      $stage = 'module'; $failureCode = 'MODULE_UNLOAD_FAILED'
      $name = Get-NebulahComponentName $console
      $module = [string]$request.name
      if ($module -notmatch '^[\x20-\x7E]{1,124}\.xex$' -or $module -match '[\\/:*?"<>|]') { throw 'Invalid module name' }
      if ((Invoke-NebulahFunction $console $name 5 @($module)) -ne 1) { throw 'Module is not managed or already released' }
      $script:modulePhase = 'module-result'
      $status = Invoke-NebulahFunction $console $name 6 @($module)
      $script:moduleStatus = '0x' + $status.ToString('X8')
      if ($status -ne 0) { throw 'Managed module release was not confirmed' }
      $script:modulePhase = 'module-inventory'
      if (-not (Wait-ModuleCount $console $module 0 20)) { throw 'Managed module remains listed after release' }
      @{ok=$true; name=$module; state='unloaded'} | ConvertTo-Json -Compress
    }
    'component-force-release' {
      $stage = 'module'; $failureCode = 'MODULE_UNLOAD_FAILED'
      $name = Get-NebulahComponentName $console
      if ($script:nebulahProtocol -notin @(0x4E424C03,0x4E424C04)) { throw 'Nebulah manager does not support force release' }
      $module = [string]$request.name
      if ($module -notmatch '^[\x20-\x7E]{1,124}\.xex$' -or $module -match '[\\/:*?"<>|]') { throw 'Invalid module name' }
      if ((Invoke-NebulahFunction $console $name 5 @($module)) -ne 2) { throw 'Module is not awaiting force release' }
      $script:modulePhase = 'module-result'
      $status = Invoke-NebulahFunction $console $name 7 @($module)
      $script:moduleStatus = '0x' + $status.ToString('X8')
      if ($status -ne 0) { throw 'Forced module release was not confirmed' }
      $script:modulePhase = 'module-inventory'
      if (-not (Wait-ModuleCount $console $module 0 20)) { throw 'Module remains listed after forced release' }
      @{ok=$true; name=$module; state='unloaded'} | ConvertTo-Json -Compress
    }
    'plugin-load' {
      $stage = 'module'; $failureCode = 'MODULE_LOAD_FAILED'
      Invoke-ModuleLoad $console ([string]$request.path) ([string]$request.sha256) ([long]$request.size) | ConvertTo-Json -Compress
    }
    'notify' {
      $stage = 'module'; $failureCode = 'CONSOLE_NOTIFY_FAILED'
      Send-ConsoleNotification $console ([string]$request.message) | ConvertTo-Json -Compress
    }
    'plugin-unload' {
      $stage = 'module'; $failureCode = 'MODULE_UNLOAD_FAILED'
      Invoke-ModuleUnload $console ([string]$request.name) | ConvertTo-Json -Compress
    }
    'power' {
      $stage = 'power'; $failureCode = 'CONSOLE_POWER_FAILED'
      $mode = [string]$request.mode
      if ($mode -eq 'warm' -or $mode -eq 'cold') {
        $connection = $console.OpenConnection($null)
        [void](Read-TelemetryReply $console $connection ('magicboot ' + $mode.ToUpperInvariant()))
      } elseif ($mode -eq 'shutdown') {
        $names = Get-ModuleNames $console
        if (-not ($names | Where-Object { $_ -ieq 'JRPC2.xex' })) { throw 'JRPC2 module unavailable' }
        [void](Invoke-JrpcReply $console 'consolefeatures ver=2 type=11 params="A\0\A\0\"')
      } else { throw 'Unsupported power operation' }
      @{accepted=$true; mode=$mode} | ConvertTo-Json -Compress
    }
    'storage' {
      $stage = 'storage'; $failureCode = 'STORAGE_DISCOVERY_FAILED'
      Find-AccessibleConsoleStorage $console | ConvertTo-Json -Depth 4 -Compress
    }
    'capacity' {
      $connection = $console.OpenConnection($null)
      $reply = Read-TelemetryReply $console $connection ('drivefreespace name="' + [string]$request.path + '"')
      $values = @{}
      foreach ($key in @('totalbyteshi','totalbyteslo','totalfreebyteshi','totalfreebyteslo')) {
        if ($reply -notmatch ('(?:^|\s)' + $key + '=(?:0x)?([0-9A-Fa-f]{1,8})(?=\s|$)')) { throw 'Capacity unavailable' }
        $values[$key] = [Convert]::ToUInt64($Matches[1],16)
      }
      $total = $values.totalbyteshi * [uint64]4294967296 + $values.totalbyteslo
      $free = $values.totalfreebyteshi * [uint64]4294967296 + $values.totalfreebyteslo
      @{total=$total; free=$free} | ConvertTo-Json -Compress
    }
    'file-info' {
      $stage = 'transfer-info'; $failureCode = 'TRANSFER_INFO_FAILED'
      $file = $console.GetDownloadFileInfo([string]$request.path)
      @{directory=$file.IsDirectory; size=$file.Size} | ConvertTo-Json -Compress
    }
    'download-file' {
      $stage = 'transfer-read'; $failureCode = 'TRANSFER_READ_FAILED'
      $file = $console.GetDownloadFileInfo([string]$request.path)
      if ($file.IsDirectory -or $file.Size -ne [long]$request.size -or $file.Size -gt 134217728) { throw 'Remote size changed' }
      $console.ReceiveFile([string]$request.local,[string]$request.path)
      if ((Get-Item -LiteralPath ([string]$request.local)).Length -ne [long]$request.size) { throw 'Downloaded size changed' }
      @{ok=$true} | ConvertTo-Json -Compress
    }
    'upload-file' {
      $stage = 'transfer-create'; $failureCode = 'TRANSFER_CREATE_FAILED'
      $local = Get-Item -LiteralPath ([string]$request.local)
      if ($local.Length -ne [long]$request.size -or $local.Length -gt 134217728) { throw 'Staged size changed' }
      $console.SendFile($local.FullName,[string]$request.path)
      @{ok=$true} | ConvertTo-Json -Compress
    }
    'upload-empty' {
      # Neighborhood COM rejected zero-byte SendFile on hardware; the normal readback and rename still follow this create step.
      $stage = 'transfer-create'; $failureCode = 'TRANSFER_CREATE_FAILED'
      $local = Get-Item -LiteralPath ([string]$request.local)
      $path = [string]$request.path
      if ($local.Length -ne 0 -or [long]$request.size -ne 0 -or $path.Length -gt 512 -or $path -match '[^\x20-\x7E]|"' -or $target -notmatch '^[A-Za-z0-9_.-]{1,253}$') { throw 'Invalid empty upload' }
      $client = New-Object System.Net.Sockets.TcpClient
      try {
        $client.Connect($target,730)
        $client.ReceiveTimeout = 3000; $client.SendTimeout = 3000
        $network = $client.GetStream()
        function Read-XbdmLine($stream) {
          $bytes = New-Object System.Collections.Generic.List[byte]
          while ($bytes.Count -lt 160) {
            $value = $stream.ReadByte()
            if ($value -lt 0) { throw 'XBDM reply incomplete' }
            if ($value -eq 10) { return [Text.Encoding]::ASCII.GetString($bytes.ToArray()) }
            $bytes.Add([byte]$value)
          }
          throw 'XBDM reply too long'
        }
        if ((Read-XbdmLine $network) -notlike '201-*') { throw 'XBDM connection refused' }
        $command = [Text.Encoding]::ASCII.GetBytes('sendfile name="' + $path + '" length=0' + "`r`n")
        $network.Write($command,0,$command.Length)
        if ((Read-XbdmLine $network) -notlike '204-*') { throw 'Empty upload refused' }
      } finally { $client.Dispose() }
      @{ok=$true} | ConvertTo-Json -Compress
    }
    'verify-upload' {
      $stage = 'transfer-readback'; $failureCode = 'TRANSFER_READBACK_FAILED'
      $file = $console.GetFileObject([string]$request.path)
      if ($file.IsDirectory -or $file.Size -ne [long]$request.size -or $file.Size -gt 134217728) { throw 'Remote size changed' }
      $temp = [IO.Path]::GetTempFileName()
      try {
        $console.ReceiveFile($temp,[string]$request.path)
        if ((Get-Item -LiteralPath $temp).Length -ne [long]$request.size) { throw 'Read-back size changed' }
        $stage = 'transfer-hash'; $failureCode = 'TRANSFER_HASH_FAILED'
        $digest = (Get-FileHash -LiteralPath $temp -Algorithm SHA256).Hash.ToLowerInvariant()
        @{sha256=$digest} | ConvertTo-Json -Compress
      } finally { Remove-Item -LiteralPath $temp -Force }
    }
    'rename-transfer' {
      $stage = 'transfer-rename'; $failureCode = 'TRANSFER_RENAME_FAILED'
      $console.RenameFile([string]$request.path,[string]$request.destination)
      @{ok=$true} | ConvertTo-Json -Compress
    }
    'delete-file' {
      $stage = 'transfer-cleanup'; $failureCode = 'TRANSFER_CLEANUP_FAILED'
      $file = $console.GetFileObject([string]$request.path)
      if ($file.IsDirectory) { throw 'Partial path is a directory' }
      $console.DeleteFile([string]$request.path)
      @{ok=$true} | ConvertTo-Json -Compress
    }
    'browse' {
      $stage = 'storage'; $failureCode = 'STORAGE_BROWSE_FAILED'
      $items = @($console.DirectoryFiles([string]$request.path) | ForEach-Object {
        @{ name=[string]$_.Name; directory=[bool]$_.IsDirectory; size=[long]$_.Size }
      })
      @{ files=$items } | ConvertTo-Json -Depth 4 -Compress
    }
    'browse-many' {
      $stage = 'storage'; $failureCode = 'STORAGE_BROWSE_FAILED'
      $listings = @(
        foreach ($folder in $request.paths) {
          try {
            $items = @($console.DirectoryFiles([string]$folder) | ForEach-Object {
              @{ name=[string]$_.Name; directory=[bool]$_.IsDirectory; size=[long]$_.Size }
            })
            @{ files=$items }
          } catch {
            # A missing/removable folder must not discard other listings.
            @{ error=$true }
          }
        }
      )
      @{ listings=$listings } | ConvertTo-Json -Depth 6 -Compress
    }
    'receive' {
      $stage = 'transfer-info'; $failureCode = 'TRANSFER_INFO_FAILED'
      $file = $console.GetDownloadFileInfo([string]$request.path)
      if ($file.IsDirectory -or $file.Size -gt 67108864 -or $file.Size -lt 24) { throw 'File outside inspection limits' }
      $stage = 'transfer-read'; $failureCode = 'TRANSFER_READ_FAILED'
      $console.ReceiveFile([string]$request.local, [string]$request.path)
      if ((Get-Item -LiteralPath ([string]$request.local)).Length -ne $file.Size) { throw 'Inspected file size changed' }
      @{ ok=$true } | ConvertTo-Json -Compress
    }
    'launch' {
      $path = [string]$request.path
      $directory = $path.Substring(0, $path.LastIndexOf('\') + 1)
      # IXboxConsole.Reboot(title, mediaDirectory, commandLine, flags).
      # Flag 0 requests a title reboot. No arbitrary command strings exposed.
      $console.Reboot($path, $directory, '', 0)
      @{ ok=$true } | ConvertTo-Json -Compress
    }
    default { throw 'Unsupported adapter operation' }
  }
} catch {
  # Do not return raw COM exceptions: these can contain console identifiers.
  if ($request.action -eq 'plugin-load' -and $_.Exception.Message -eq 'Module already loaded') {
    $failureCode = 'MODULE_ALREADY_LOADED'
  }
  $cause = $_.Exception
  while ($null -ne $cause.InnerException) { $cause = $cause.InnerException }
  $hresult = '0x' + $cause.HResult.ToString('X8')
  $diagnostic = @{code=$failureCode; stage=$stage; architecture=$architecture; hresult=$hresult}
  if ($request.action -in @('plugin-load','plugin-unload','component-load','component-unload','component-force-release','component-input-pulse') -and $script:modulePhase -in @('module-path','module-probe','module-file','module-handle','module-resolve','module-call','module-result','module-inventory')) {
    $diagnostic.phase = $script:modulePhase
    if ($request.action -in @('plugin-load','component-load') -and $script:modulePathMode -in @('selected-path','verified-usb-alias')) { $diagnostic.path_mode = $script:modulePathMode }
    if ($script:modulePhase -in @('module-result','module-inventory') -and $script:moduleStatus -match '^0x[0-9A-F]{8}$') {
      $diagnostic.module_status = $script:moduleStatus
    }
  }
  @{ diagnostic=$diagnostic } | ConvertTo-Json -Depth 3 -Compress
  exit 1
} finally {
  if ($null -ne $connection) { try { $console.CloseConnection($connection) } catch {} }
  if ($null -ne $nativeConsole) { try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($nativeConsole) } catch {} }
  if ($null -ne $manager) { try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($manager) } catch {} }
}
