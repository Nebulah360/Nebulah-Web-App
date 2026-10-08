# Observe module names only. Never return addresses or raw debug-monitor replies.
function Get-ConsoleModuleInventory($Console) {
  $names = @(); $comRejected = 0
  try {
    $view = $Console.DebugTarget
    foreach ($item in @($view.Modules)) {
      $name = [string]$item.Name
      if ([string]::IsNullOrWhiteSpace($name) -or $name.Length -gt 260 -or $name -match '[\x00-\x1f]') { $comRejected++; continue }
      $names += @{name=$name}
    }
    if ($names.Count -gt 0 -and $comRejected -eq 0) {
      return @{modules=@($names); source='xdevkit'; state='observed'}
    }
  } catch { $comRejected++ }
  $fallback = @(); $rejected = 0; $connection = $null; $complete = $false
  try {
    $connection = $Console.OpenConnection($null)
    $reply = ''
    [void]$Console.SendTextCommand($connection, 'modules', [ref]$reply)
    if ($reply -notmatch '^202[- ]') { throw 'Module command unavailable' }
    $clock = [Diagnostics.Stopwatch]::StartNew()
    for ($index = 0; $index -le 512; $index++) {
      if ($clock.Elapsed.TotalSeconds -gt 15) { break }
      $line = ''
      [void]$Console.ReceiveSocketLine($connection, [ref]$line)
      if ($line -eq '.') { $complete=$true; break }
      if ($index -eq 512) { break }
      if ($line.Length -le 4096 -and $line -match '(?:^|\s)name="([^"\x00-\x1f]{1,260})"(?=\s|$)') {
        $fallback += @{name=$Matches[1]}
      } else { $rejected++ }
    }
  } catch { $complete=$false }
  finally { if ($null -ne $connection) { try { [void]$Console.CloseConnection($connection) } catch {} } }
  if ($fallback.Count -gt 0 -or $complete) {
    $state = if ($complete -and $rejected -eq 0) { 'observed' } else { 'partial' }
    return @{modules=@($fallback); source='xbdm'; state=$state; rejected=$rejected}
  }
  if ($names.Count -gt 0) { return @{modules=@($names); source='xdevkit'; state='partial'; rejected=$comRejected} }
  return @{modules=@(); source='none'; state='unavailable'}
}

function Convert-ConsoleDrives($Value) {
  # IXboxConsole.Drives is a semicolon-delimited BSTR, not a COM collection.
  $roots = @()
  foreach ($item in @($Value)) {
    foreach ($part in ([string]$item -split ';')) {
      $name = $part.Trim()
      if ($name -match '^([A-Za-z0-9_]+)(?::\\?)?$') {
        $root = $Matches[1] + ':\'
        if ($roots -notcontains $root) { $roots += $root }
      }
    }
  }
  return $roots
}
# Read-only protocol mappings. See docs/TELEMETRY.md for pinned sources.
function Read-TelemetryReply($Console, $Connection, [string]$Command) {
  $response = ''
  try { [void]$Console.SendTextCommand($Connection, $Command, [ref]$response) }
  catch { throw (Get-TelemetryFailure $_) }
  if ($response -match '^202[- ]') {
    # XBDM multi-line responses must be drained before another command.
    $lines = @()
    for ($n = 0; $n -lt 32; $n++) {
      $line = ''
      try { [void]$Console.ReceiveSocketLine($Connection, [ref]$line) } catch { throw 'COMMAND_FAILED' }
      if ($line -eq '.') { return ($lines -join "`n") }
      if ($line.Length -gt 1024) { throw 'INVALID_RESPONSE' }
      $lines += $line
    }
    throw 'INVALID_RESPONSE'
  }
  if ($response -match '^4\d\d[- ]|DEBUG|error=') { throw 'COMMAND_REJECTED' }
  if ($response -match '^200[- ]+\s*([^\r\n]*)\s*$') { return $Matches[1].Trim() }
  if ($response -match '^4\d\d[- ]|DEBUG|error=') { throw 'COMMAND_REJECTED' }
  throw 'INVALID_RESPONSE'
}
function Convert-TelemetryNumber([string]$Value, [int]$Base) {
  if (($Base -eq 16 -and $Value -notmatch '^(?:0x)?[0-9a-fA-F]{1,8}$') -or
      ($Base -eq 10 -and $Value -notmatch '^\d{1,5}$')) { throw 'INVALID_RESPONSE' }
  return [Convert]::ToUInt32(($Value -replace '^0x',''), $Base)
}
function Get-TelemetryFailure($ErrorRecord) {
  if ($ErrorRecord.FullyQualifiedErrorId -eq 'MethodNotFound') { return 'COM_BINDING_FAILED' }
  $exception = $ErrorRecord.Exception
  while ($null -ne $exception.InnerException) { $exception = $exception.InnerException }
  # Safe numeric error classification; never return COM messages/identifiers.
  if ($exception.HResult -in @(-2147352573,-2147352570,-2147467262)) { return 'COM_BINDING_FAILED' }
  if ($exception.HResult -eq -2099642361) { return 'COMMAND_REJECTED' } # 0x82DA0007
  if ($exception -is [System.Management.Automation.MethodException] -or
      $exception -is [System.MissingMethodException] -or
      $exception -is [System.ArgumentException]) { return 'COM_BINDING_FAILED' }
  $code = $exception.Message
  if ($code -in @('COMMAND_FAILED','COMMAND_REJECTED','INVALID_RESPONSE','OUT_OF_RANGE','COM_BINDING_FAILED')) { return $code }
  return 'COMMAND_FAILED'
}
function Get-ConsoleTelemetry($Console) {
  $result = @{
    adapter_version=10
    type='Unavailable'; kernel='Unavailable'; motherboard='Unavailable'
    temperatures=@{cpu=$null; gpu=$null; edram=$null; motherboard=$null}
    current_title=@{executable=$null; title_id=$null}
    telemetry_fields=@{}
    plugin_support=@{observed=@(); module_scan='unavailable'; jrpc='unavailable'}
  }
  $fields = $result.telemetry_fields
  foreach ($field in @('type','kernel','motherboard','cpu','gpu','edram','board_temperature','executable','title_id')) {
    $fields[$field] = @{state='UNAVAILABLE'; source='none'}
  }
  try {
    $kind = [string]$Console.ConsoleType
    $kinds = @{'0'='Development kit'; '1'='Test kit'; '2'='Reviewer kit'; 'DevelopmentKit'='Development kit'; 'TestKit'='Test kit'; 'ReviewerKit'='Reviewer kit'}
    if ($kinds.ContainsKey($kind)) {
      $result.type = $kinds[$kind]; $fields.type = @{state='OK'; source='xdevkit'}
    }
  } catch {}
  try {
    $path = [string]$Console.RunningProcessInfo.ProgramName
    if ($path -and $path.Length -le 512 -and $path -notmatch '[\x00-\x1f]') {
      $result.current_title.executable = $path; $fields.executable = @{state='OK'; source='xdevkit'}
    }
  } catch {}
  # Observe known plugin filenames only. An observed module is not proof that
  # its RPC handler works; successful replies determine support separately.
  try {
    $known = @()
    foreach ($module in $Console.DebugTarget.Modules) {
      $name = ([string]$module.Name -split '[\\/]')[-1].ToLowerInvariant()
      if ($name -in @('jrpc.xex','jrpc2.xex','rpc.xex','xrpc.xex')) { $known += $name }
    }
    $result.plugin_support.observed = @($known | Select-Object -Unique)
    $result.plugin_support.module_scan = 'ok'
  } catch {}
  $connection = $null
  try {
    # Same default command handler as JRPC_Client.Connect. Timeouts are set by
    # the caller with guarded assignments; unsupported setters must not skip reads.
    try { $connection = $Console.OpenConnection($null) } catch { if ((Get-TelemetryFailure $_) -eq 'COM_BINDING_FAILED') { throw 'COM_BINDING_FAILED' }; throw 'CHANNEL_FAILED' }
    $queries = @(
      @{field='cpu'; type=15; sensor=0; base=16},
      @{field='gpu'; type=15; sensor=1; base=16},
      @{field='edram'; type=15; sensor=2; base=16},
      @{field='board_temperature'; type=15; sensor=3; base=16},
      @{field='kernel'; type=13; base=10},
      @{field='title_id'; type=16; base=16},
      @{field='motherboard'; type=17}
    )
    foreach ($query in $queries) {
      $field = $query.field
      try {
        $params = 'A\0\A\0\'
        if ($query.type -eq 15) { $params = 'A\0\A\1\1\' + $query.sensor + '\' }
        $command = 'consolefeatures ver=2 type=' + $query.type + ' params="' + $params + '"'
        $payload = Read-TelemetryReply $Console $connection $command
        if ($query.type -eq 17) {
          if ($payload -notmatch '^(Xenon|Zephyr|Falcon|Opus|Jasper|Trinity|Corona|Winchester)$') { throw 'INVALID_RESPONSE' }
          $result.motherboard = $payload
        } else {
          $value = Convert-TelemetryNumber $payload $query.base
          switch ($query.type) {
            15 {
              if ($value -eq 0 -or $value -gt 125) { throw 'OUT_OF_RANGE' }
              $sensorName = @('cpu','gpu','edram','motherboard')[$query.sensor]
              $result.temperatures[$sensorName] = $value
            }
            13 {
              if ($value -eq 0 -or $value -gt 65535) { throw 'OUT_OF_RANGE' }
              $result.kernel = [string]$value
            }
            16 { $result.current_title.title_id = $value.ToString('X8') }
          }
        }
        $fields[$field] = @{state='OK'; source='jrpc'}
      } catch { $fields[$field] = @{state=(Get-TelemetryFailure $_); source='jrpc'} }
    }
    # Native XBDM reads also work with XRPC-only installations. Use a fresh
    # channel so a failed plugin response cannot corrupt multiline framing.
    if ($null -ne $connection) { try { [void]$Console.CloseConnection($connection) } catch {} }
    $connection = $null
    try { $connection = $Console.OpenConnection($null) } catch { if ((Get-TelemetryFailure $_) -eq 'COM_BINDING_FAILED') { throw 'COM_BINDING_FAILED' }; throw 'CHANNEL_FAILED' }
    if ($result.kernel -eq 'Unavailable' -or $result.motherboard -eq 'Unavailable') {
      try {
        $body = Read-TelemetryReply $Console $connection 'systeminfo'
        if ($result.kernel -eq 'Unavailable' -and $body -match '(?im)(?:^|\s)Krnl="?(\d{1,2}\.\d{1,2}\.\d{1,5}\.\d{1,5})(?:"|\s|$)') {
          $result.kernel = $Matches[1]; $fields.kernel = @{state='OK'; source='xbdm'}
        }
        if ($result.motherboard -eq 'Unavailable' -and $body -match '(?im)(?:^|\s)System="?(Xenon|Zephyr|Falcon|Opus|Jasper|Trinity|Corona|Winchester)(?:"|\s|$)') {
          $result.motherboard = $Matches[1]; $fields.motherboard = @{state='OK'; source='xbdm'}
        }
      } catch {}
      # A timed-out/incomplete multiline response must not poison the next read.
      try { [void]$Console.CloseConnection($connection) } catch {}
      $connection = $null
      try { $connection = $Console.OpenConnection($null) } catch { if ((Get-TelemetryFailure $_) -eq 'COM_BINDING_FAILED') { throw 'COM_BINDING_FAILED' }; throw 'CHANNEL_FAILED' }
    }
    if (-not $result.current_title.executable) {
      try {
        $body = Read-TelemetryReply $Console $connection 'xbeinfo running'
        if ($body -notmatch '(?m)(?:^|\s)name="([^"\r\n]{1,512})"') { throw 'INVALID_RESPONSE' }
        $result.current_title.executable = $Matches[1]
        $fields.executable = @{state='OK'; source='xbdm'}
      } catch { $fields.executable = @{state=(Get-TelemetryFailure $_); source='xbdm'} }
    }
  } catch {
    $channelState = if ((Get-TelemetryFailure $_) -eq 'COM_BINDING_FAILED') { 'COM_BINDING_FAILED' } else { 'CHANNEL_FAILED' }
    foreach ($field in @('cpu','gpu','edram','board_temperature','kernel','title_id','motherboard')) {
      if ($fields[$field].state -eq 'UNAVAILABLE') { $fields[$field] = @{state=$channelState; source='jrpc'} }
    }
  } finally {
    if ($null -ne $connection) { try { [void]$Console.CloseConnection($connection) } catch {} }
  }
  $successful = @('cpu','gpu','edram','board_temperature','kernel','title_id','motherboard') | Where-Object { $fields[$_].state -eq 'OK' -and $fields[$_].source -eq 'jrpc' }
  if (@($successful).Count -gt 0) { $result.plugin_support.jrpc = 'responding' }
  elseif ($fields.cpu.state -eq 'COMMAND_REJECTED') { $result.plugin_support.jrpc = 'rejected' }
  else { $result.plugin_support.jrpc = 'failed' }
  return $result
}

# Read-only fallback through the existing Neighborhood command channel.
# Never invent common drive letters when discovery returns no roots.
function Get-ConsoleStorage($Console) {
  $channel = $null
  try {
    $roots = @(Convert-ConsoleDrives $Console.Drives)
    if ($roots.Count) { return @{ drives=$roots; source='xdevkit'; state='OK' } }
  } catch {}
  try {
    $channel = $Console.OpenConnection($null)
    $reply = Read-TelemetryReply $Console $channel 'drivelist'
    $names = @()
    foreach ($line in ($reply -split "`n")) {
      if ($line -match '^\s*drivename="([A-Za-z0-9_]+)(?::\\?)?"\s*$') { $names += $Matches[1] }
      elseif (-not [string]::IsNullOrWhiteSpace($line)) { throw 'INVALID_RESPONSE' }
    }
    $roots = @(Convert-ConsoleDrives $names)
    return @{ drives=$roots; source='xbdm'; state=$(if ($roots.Count) {'OK'} else {'EMPTY'}) }
  } catch {
    return @{ drives=@(); source='none'; state='FAILED' }
  } finally {
    if ($null -ne $channel) { try { $Console.CloseConnection($channel) } catch {} }
  }
}

# Dash's discovery rule: presence is established by a root access probe.
# The PC cannot mount Dash's title-local Neb* aliases; use reported roots only.
function Find-AccessibleConsoleStorage($Console) {
  $inventory = Get-ConsoleStorage $Console
  $accessible = @(); $checked = 0; $unavailable = 0
  $timer = [Diagnostics.Stopwatch]::StartNew()
  foreach ($root in @($inventory.drives)) {
    if ($checked -ge 32 -or $timer.Elapsed.TotalSeconds -ge 12) { break }
    $checked++
    try {
      if ($Console.DirectoryExists([string]$root)) { $accessible += $root }
      else { $unavailable++ }
    } catch { $unavailable++ }
  }
  $state = if ($checked -lt @($inventory.drives).Count) { 'PARTIAL' }
           elseif ($accessible.Count) { 'OK' }
           elseif ($checked -gt 0) { 'INACCESSIBLE' }
           else { $inventory.state }
  return @{ drives=$accessible; storage=@{ source=$inventory.source; state=$state; checked=$checked; unavailable=$unavailable } }
}
