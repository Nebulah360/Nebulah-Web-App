# Local registration only. Never call DefaultConsole, OpenConsole or a console API.
$ErrorActionPreference = 'Stop'
$manager = $null
try {
  $type = [Type]::GetTypeFromCLSID([Guid]'A5EB45D8-F3B6-49B9-984A-0D313AB60342')
  $manager = [Activator]::CreateInstance($type)
  if ($null -eq $manager) { exit 1 }
} catch { exit 1 }
finally {
  if ($null -ne $manager) { try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($manager) } catch {} }
}
exit 0
