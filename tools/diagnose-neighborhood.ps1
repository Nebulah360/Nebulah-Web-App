# Read-only local COM diagnostic. Never emit console identifiers or raw errors.
$ErrorActionPreference = 'Stop'
function Write-Failure([string]$Step, $Record) {
  Write-Output ($Step + ': FAILED')
  $exception = $Record.Exception
  $depth = 0
  while ($null -ne $exception -and $depth -lt 8) {
    Write-Output ('  Exception: ' + $exception.GetType().FullName + ' / HRESULT 0x' + $exception.HResult.ToString('X8'))
    $exception = $exception.InnerException
    $depth++
  }
}
function Test-ComInterface($Object, [string]$Label, [string]$Guid) {
  $unknown = [IntPtr]::Zero; $pointer = [IntPtr]::Zero
  try {
    $unknown = [Runtime.InteropServices.Marshal]::GetIUnknownForObject($Object)
    $iid = [Guid]$Guid
    $hr = [Runtime.InteropServices.Marshal]::QueryInterface($unknown, [ref]$iid, [ref]$pointer)
    Write-Output ($Label + ': HRESULT 0x' + $hr.ToString('X8'))
  } catch { Write-Failure $Label $_ }
  finally {
    if ($pointer -ne [IntPtr]::Zero) { [void][Runtime.InteropServices.Marshal]::Release($pointer) }
    if ($unknown -ne [IntPtr]::Zero) { [void][Runtime.InteropServices.Marshal]::Release($unknown) }
  }
}
Write-Output 'Nebulah COM diagnostic: 8 (module scan and directory entry shapes)'
Write-Output ('PowerShell: ' + $PSVersionTable.PSVersion.ToString())
Write-Output ('Process architecture: ' + ([IntPtr]::Size * 8) + '-bit')
$manager = $null; $native = $null; $wrapped = $null; $connection = $null
$step = 'Load local wrapper'
try {
  Add-Type -Path "$PSScriptRoot/../bridge/ComDispatch.cs"
  Write-Output 'Wrapper compile: OK'
  $step = 'Create manager'
  $manager = [Activator]::CreateInstance([Type]::GetTypeFromCLSID([Guid]'A5EB45D8-F3B6-49B9-984A-0D313AB60342'))
  $step = 'Read default console'
  $target = [string]$manager.DefaultConsole
  Write-Output ('Default configured: ' + [bool]$target)
  if (-not $target) { throw 'Default unavailable' }
  $step = 'Open console'
  $native = $manager.OpenConsole($target)
  Write-Output ('Console object returned: ' + ($null -ne $native))
  if ($null -eq $native) { throw 'Console unavailable' }
  Write-Output ('Native object type: ' + $native.GetType().FullName)
  Test-ComInterface $native 'Console interface' '75DD80A9-5A33-42D4-8A39-AB07C9B17CC3'
  Test-ComInterface $native 'Automation interface' '00020400-0000-0000-C000-000000000046'
  try {
    Add-Type -Path "$PSScriptRoot/ComMetadata.cs"
    [NebulahDiagnostics.Probe]::Read($native, $false) | ForEach-Object { Write-Output $_ }
    [NebulahDiagnostics.Probe]::Read($native, $true) | ForEach-Object { Write-Output $_ }
  } catch { Write-Failure 'Metadata probe' $_ }
  $wrapped = New-Object Nebulah.ConsoleDispatch -ArgumentList $native
  try { $wrapped.ConnectTimeout=2000; $wrapped.ConversationTimeout=2000; Write-Output 'Timeout properties: OK' } catch { Write-Failure 'Timeout properties' $_ }
  try {
    $drives = $wrapped.Drives
    Write-Output ('Drives property readable: True; nonempty: ' + (-not [string]::IsNullOrWhiteSpace($drives)))
  } catch { Write-Failure 'Drives property' $_ }
  try {
    . "$PSScriptRoot/../bridge/telemetry.ps1"
    $storage = Get-ConsoleStorage $wrapped
    Write-Output ('Storage discovery: ' + $storage.source + ' / ' + $storage.state)
    Write-Output ('Storage root count: ' + @($storage.drives).Count)
    if (@($storage.drives).Count -gt 0) {
      $items = @($wrapped.DirectoryFiles([string]$storage.drives[0]))
      Write-Output ('First storage root browse: OK; entries: ' + $items.Count)
      $full = @($items | Where-Object { $_.Name -match '^[A-Za-z0-9_]+:\\' }).Count
      Write-Output ('Entry shape counts: full paths=' + $full + '; other names=' + ($items.Count - $full))
    }
  } catch { Write-Failure 'First storage root browse' $_ }
  try {
    $moduleView = $wrapped.DebugTarget
    $moduleItems = @($moduleView.Modules)
    $validNames = 0; $emptyNames = 0; $invalidNames = 0
    foreach ($item in $moduleItems) {
      $name = [string]$item.Name
      if ([string]::IsNullOrWhiteSpace($name)) { $emptyNames++ }
      elseif ($name.Length -gt 260 -or $name -match '[\x00-\x1f]') { $invalidNames++ }
      else { $validNames++ }
    }
    Write-Output ('Module scan: returned=' + $moduleItems.Count + '; valid names=' + $validNames + '; empty names=' + $emptyNames + '; invalid names=' + $invalidNames)
    # Compare the adapter's JSON shape without printing any module names.
    $projected = @($moduleItems | ForEach-Object { @{name=[string]$_.Name} })
    $roundtrip = @{modules=$projected} | ConvertTo-Json -Depth 4 -Compress | ConvertFrom-Json
    Write-Output ('Module JSON count: ' + @($roundtrip.modules).Count)
  } catch { Write-Failure 'Module scan' $_ }
  try {
    . "$PSScriptRoot/../bridge/telemetry.ps1"
    $inventory = Get-ConsoleModuleInventory $wrapped
    Write-Output ('Module inventory: source=' + $inventory.source + '; state=' + $inventory.state + '; entries=' + @($inventory.modules).Count)
  } catch { Write-Failure 'Module inventory' $_ }
  try {
    $connection = $wrapped.OpenConnection($null)
    Write-Output 'Command channel: OK'
  } catch { Write-Failure 'Command channel' $_ }
} catch { Write-Failure $step $_ }
finally {
  if ($null -ne $connection) { try { $wrapped.CloseConnection($connection) } catch {} }
  foreach ($object in @($native,$manager)) {
    if ($null -ne $object) { try { if ([Runtime.InteropServices.Marshal]::IsComObject($object)) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($object) } } catch {} }
  }
}
Write-Output 'End diagnostic. No plugin settings, files or private console information were requested.'

