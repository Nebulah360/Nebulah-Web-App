$ErrorActionPreference = 'Stop'

function Test-PrivateIPv4([System.Net.IPAddress]$Address) {
  if ($Address.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { return $false }
  $octets = $Address.GetAddressBytes()
  return ($octets[0] -eq 10) -or
    ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31) -or
    ($octets[0] -eq 192 -and $octets[1] -eq 168)
}

$candidates = @(
  foreach ($adapter in [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
    if ($adapter.OperationalStatus -ne [System.Net.NetworkInformation.OperationalStatus]::Up) { continue }
    if ($adapter.NetworkInterfaceType -notin @([System.Net.NetworkInformation.NetworkInterfaceType]::Ethernet,
                                               [System.Net.NetworkInformation.NetworkInterfaceType]::Wireless80211)) { continue }
    if (($adapter.Name + ' ' + $adapter.Description) -match '(?i)vEthernet|Hyper-V|VirtualBox|VMware|WSL|Docker|VPN|Tailscale|WireGuard') { continue }
    $properties = $adapter.GetIPProperties()
    $gateway = @($properties.GatewayAddresses | Where-Object {
      $_.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork
    }).Count -gt 0
    foreach ($address in $properties.UnicastAddresses) {
      if (-not (Test-PrivateIPv4 $address.Address)) { continue }
      [pscustomobject]@{ IP=$address.Address.IPAddressToString; Interface=$adapter.Name;
        Preferred=([int]$gateway * 2 + [int]($adapter.NetworkInterfaceType -eq [System.Net.NetworkInformation.NetworkInterfaceType]::Wireless80211)) }
    }
  }
)
$candidates = @($candidates | Sort-Object @{Expression='Preferred';Descending=$true}, Interface, IP)
if (-not $candidates) {
  [Console]::Error.WriteLine('No usable private Wi-Fi/Ethernet IPv4 address found. Connect this PC to the same trusted network as your phone.')
  exit 1
}
if ($candidates.Count -gt 1 -and $candidates[0].Preferred -eq $candidates[1].Preferred) {
  Write-Host 'Choose the PC network shared with your phone:'
  for ($i=0; $i -lt $candidates.Count; $i++) { Write-Host "  $($i+1). $($candidates[$i].IP) ($($candidates[$i].Interface))" }
  $selection = Read-Host 'Number'
  $choice = 0
  if (-not [int]::TryParse($selection,[ref]$choice) -or $choice -lt 1 -or $choice -gt $candidates.Count) {
    [Console]::Error.WriteLine('No network selected.'); exit 1
  }
  $candidates[$choice-1].IP
} else {
  $candidates[0].IP
}
