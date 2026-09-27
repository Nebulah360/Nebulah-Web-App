# Run with the Windows PowerShell architecture matching installed XDevkit COM.
$ErrorActionPreference = 'Stop'
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$manager = $null; $console = $null; $connection = $null
function Read-FeatureHex([string]$command) {
  $response = ""
  $console.SendTextCommand($connection, $command, [ref]$response)
  if ($response -notmatch "^200[- ]+\s*(?:0x)?([0-9a-fA-F]{1,8})\s*$") { throw "Unsupported telemetry response" }
  return [Convert]::ToUInt32($Matches[1], 16)
}
try {
  $manager = New-Object -ComObject 'XDevkit.XboxManager'
  $target = [string]$request.target
  if ([string]::IsNullOrWhiteSpace($target)) { $target = $manager.DefaultConsole }
  $console = $manager.OpenConsole($target)
  switch ($request.action) {
    'status' {
      # Deliberate allowlist. Never serialize a COM console/debug object.
      $drives = @($console.Drives | ForEach-Object { ([string]$_).TrimEnd('\', ':') + ':\' })
      $kind = 'Unavailable'; $kernel = 'Unavailable'
      try { $kind = [string]$console.ConsoleType } catch {}
      try { $kernel = [string]$console.KernelVersion } catch {}
      $temperatures = @{ cpu=$null; gpu=$null; edram=$null; motherboard=$null }
      $executable = $null; $titleId = $null
      try { $executable = [string]$console.RunningProcessInfo.ProgramName } catch {}
      # Optional read-only JRPC v2 consolefeatures commands. Never load a plugin,
      # call arbitrary addresses, or query console identity/private material.
      try {
        $console.ConnectTimeout = 2000
        $console.ConversationTimeout = 2000
        $connection = $console.OpenConnection('')
        $sensors = @('cpu', 'gpu', 'edram', 'motherboard')
        for ($i = 0; $i -lt 4; $i++) {
          try {
            $cmd = 'consolefeatures ver=2 type=15 params="A\0\A\1\1\' + $i + '\"'
            $value = Read-FeatureHex $cmd
            if ($value -gt 0 -and $value -le 125) { $temperatures[$sensors[$i]] = $value }
          } catch { }
        }
        try { $titleId = (Read-FeatureHex 'consolefeatures ver=2 type=16 params="A\0\A\0\"').ToString('X8') } catch {}
      } catch { }
      @{ type=$kind; kernel=$kernel; drives=$drives; temperatures=$temperatures; current_title=@{executable=$executable; title_id=$titleId} } | ConvertTo-Json -Depth 4 -Compress
    }
    'browse' {
      $items = @($console.DirectoryFiles([string]$request.path) | ForEach-Object {
        @{ name=[string]$_.Name; directory=[bool]$_.IsDirectory; size=[long]$_.Size }
      })
      @{ files=$items } | ConvertTo-Json -Depth 4 -Compress
    }
    'receive' {
      $file = $console.GetFileObject([string]$request.path)
      if ($file.IsDirectory -or $file.Size -gt 67108864 -or $file.Size -lt 24) { throw 'File outside inspection limits' }
      $console.ReceiveFile([string]$request.local, [string]$request.path)
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
  [Console]::Error.WriteLine('Neighborhood operation failed. Check XDevkit registration, console reachability, and adapter compatibility.')
  exit 1
} finally {
  if ($null -ne $connection) { try { $console.CloseConnection($connection) } catch {} }
  if ($null -ne $console) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($console) }
  if ($null -ne $manager) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($manager) }
}
