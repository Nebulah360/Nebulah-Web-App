# Run with the Windows PowerShell architecture matching installed XDevkit COM.
$ErrorActionPreference = 'Stop'
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$manager = $null; $console = $null
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
      @{ type=$kind; kernel=$kernel; drives=$drives } | ConvertTo-Json -Compress
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
  if ($null -ne $console) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($console) }
  if ($null -ne $manager) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($manager) }
}
