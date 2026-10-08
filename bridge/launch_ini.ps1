# Scoped launch.ini file operations. Only the verified active-root Python flow calls these.
function Get-SmallConsoleFile($Console, [string]$Path) {
  $file = $Console.GetDownloadFileInfo($Path)
  if ($file.IsDirectory -or $file.Size -lt 1 -or $file.Size -gt 131072) { throw 'launch.ini file outside read limits' }
  $temp = [IO.Path]::GetTempFileName()
  try {
    $Console.ReceiveFile($temp, $Path)
    if ((Get-Item -LiteralPath $temp).Length -ne $file.Size) { throw 'Console file changed during read' }
    return ,[IO.File]::ReadAllBytes($temp)
  } finally { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
}

function Get-BytesSha256([byte[]]$Bytes) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try { return [BitConverter]::ToString($sha.ComputeHash($Bytes)).Replace('-','').ToLowerInvariant() }
  finally { $sha.Dispose() }
}

function Assert-LaunchIniRootPath([string]$Path) {
  if ($Path -notmatch '^[A-Za-z0-9_]+:\\launch\.ini$') { throw 'Expected a storage-root launch.ini' }
}

function Get-LaunchIniSnapshot($Console, [string]$Path) {
  Assert-LaunchIniRootPath $Path
  $bytes = Get-SmallConsoleFile $Console $Path
  return @{sha256=(Get-BytesSha256 $bytes); size=$bytes.Length; data=[Convert]::ToBase64String($bytes)}
}

function Test-ConsoleFile($Console, [string]$Path) {
  try { $null = $Console.GetFileObject($Path); return $true } catch { return $false }
}

function Save-LaunchIniFile($Console, [string]$Path, [string]$ExpectedSha256, [string]$NewSha256, [string]$Local) {
  Assert-LaunchIniRootPath $Path
  if ($ExpectedSha256 -cnotmatch '^[0-9a-f]{64}$' -or $NewSha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Measured launch.ini hashes required' }
  $source = Get-Item -LiteralPath $Local
  if ($source.Length -lt 1 -or $source.Length -gt 131072) { throw 'Replacement launch.ini outside write limits' }
  if ((Get-FileHash -LiteralPath $Local -Algorithm SHA256).Hash.ToLowerInvariant() -cne $NewSha256) { throw 'Replacement launch.ini changed' }
  if ((Get-BytesSha256 (Get-SmallConsoleFile $Console $Path)) -cne $ExpectedSha256) {
    return @{state='changed'}
  }
  $tag = [Guid]::NewGuid().ToString('N').Substring(0,12)
  $root = $Path.Substring(0,$Path.LastIndexOf('\')+1)
  $partial = $root + 'launch.ini.nebulah-' + $tag + '.new'
  $backup = $root + 'launch.ini.nebulah-' + $tag + '.bak'
  try {
    $Console.SendFile($source.FullName, $partial)
    if ((Get-BytesSha256 (Get-SmallConsoleFile $Console $partial)) -cne $NewSha256) { throw 'Staged launch.ini did not match' }
    if ((Get-BytesSha256 (Get-SmallConsoleFile $Console $Path)) -cne $ExpectedSha256) { return @{state='changed'; partial_path=$partial} }
    $Console.RenameFile($Path, $backup)
    if ((Get-BytesSha256 (Get-SmallConsoleFile $Console $backup)) -cne $ExpectedSha256) { throw 'Backup differs from selected launch.ini' }
    $Console.RenameFile($partial, $Path)
    if ((Get-BytesSha256 (Get-SmallConsoleFile $Console $Path)) -cne $NewSha256) { throw 'Final launch.ini verification failed' }
    return @{state='saved'; backup_path=$backup; sha256=$NewSha256}
  } catch {
    $restored = $false
    if ((Test-ConsoleFile $Console $backup) -and -not (Test-ConsoleFile $Console $Path)) {
      try { $Console.RenameFile($backup, $Path); $restored = (Get-BytesSha256 (Get-SmallConsoleFile $Console $Path)) -ceq $ExpectedSha256 } catch {}
    }
    $activeMatchesOriginal = $false
    if (Test-ConsoleFile $Console $Path) {
      try { $activeMatchesOriginal = (Get-BytesSha256 (Get-SmallConsoleFile $Console $Path)) -ceq $ExpectedSha256 } catch {}
    }
    return @{state=$(if ($activeMatchesOriginal) {'failed'} else {'uncertain'}); restored=$restored;
             backup_path=$(if (Test-ConsoleFile $Console $backup) {$backup} else {$null}); partial_path=$(if (Test-ConsoleFile $Console $partial) {$partial} else {$null})}
  }
}
