param([string]$Address, [ValidateRange(1,65535)][int]$Port=8765)
$ErrorActionPreference = 'Stop'

try {
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Right-click Allow Phone Through Firewall.cmd and choose Run as administrator. This creates one Windows Private-network rule.'
  }
  if (-not $Address) {
    $Address = & (Join-Path $PSScriptRoot 'phone-host.ps1')
    if (-not $Address) { throw 'No private PC address was found.' }
  }
  $parsed = $null
  if (-not [System.Net.IPAddress]::TryParse($Address, [ref]$parsed) -or
      $parsed.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'Choose a private IPv4 address assigned to this PC.'
  }
  $parts = $parsed.GetAddressBytes()
  $private = ($parts[0] -eq 10) -or
    ($parts[0] -eq 172 -and $parts[1] -ge 16 -and $parts[1] -le 31) -or
    ($parts[0] -eq 192 -and $parts[1] -eq 168)
  if (-not $private) { throw 'Only a private IPv4 address is allowed.' }
  $local = @([System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | ForEach-Object {
    $_.GetIPProperties().UnicastAddresses | ForEach-Object { $_.Address.IPAddressToString }
  })
  if ($Address -notin $local) { throw 'The selected IPv4 address is not assigned to this PC.' }
  $profile = Get-NetFirewallProfile -Name Private
  if ($profile.AllowLocalFirewallRules -eq $false) {
    throw 'Windows policy blocks local firewall rules. Ask the network administrator to allow this Private-network port.'
  }

  $name = "Nebulah Link phone TCP $Port $Address"
  $existing = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
  if ($existing) {
    Write-Host "Firewall rule already exists: $name"
    exit 0
  }
  New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $Port -LocalAddress $Address -RemoteAddress LocalSubnet -Profile Private | Out-Null
  Write-Host "Allowed TCP $Port to $Address from the local subnet on Private networks only."
  Write-Host "Phone URL: http://${Address}:$Port"
} catch {
  Write-Host ("Phone firewall setup stopped: " + $_.Exception.Message) -ForegroundColor Red
  exit 1
}
