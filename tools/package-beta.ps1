param([switch]$Preview)

$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$git = @(git -c "safe.directory=$project" -C $project status --porcelain)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect repository state.' }
if ($git.Count -and -not $Preview) { throw 'Commit the tested beta before packaging. Use -Preview only for a local trial archive.' }

$commit = (git -c "safe.directory=$project" -C $project rev-parse --short=12 HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the beta commit.' }
$paths = @(git -c "safe.directory=$project" -C $project ls-files --cached -- `
  'Start Nebulah Link.cmd' 'Allow Phone Through Firewall.cmd' `
  'README.md' 'requirements.txt' `
  'bridge' 'dist' 'registry' 'support' 'tools')
if ($LASTEXITCODE -ne 0 -or -not $paths.Count) { throw 'Cannot list beta files.' }
$paths = @($paths | Where-Object { $_ -eq 'README.md' -or $_ -notmatch '(^|/)README\.md$' })
$required = @('Start Nebulah Link.cmd','bridge/server.py','bridge/app_settings.py',
  'dist/index.html','dist/app.js','dist/companion.js','support/errors.json')
foreach ($path in $required) { if ($path -notin $paths) { throw "Missing beta file: $path" } }
foreach ($path in $paths) {
  if ($path -match '(^|/)(\.local|Backup|tests|agent|docs)/|(^|/)ROADMAP\.md$|\.(xex|dll|bin|pyc)$' -or
      -not [IO.File]::Exists((Join-Path $project $path))) { throw "Invalid beta file: $path" }
}

$label = if ($Preview) { "$commit-preview" } else { $commit }
$outputDir = Join-Path $project '.local\releases'
[IO.Directory]::CreateDirectory($outputDir) | Out-Null
$output = Join-Path $outputDir "Nebulah-Link-beta-$label.zip"
if (Test-Path -LiteralPath $output) { throw "Archive already exists: $output" }
# Archive committed blobs so Windows line-ending conversion cannot change release bytes.
& git -c "safe.directory=$project" -c core.autocrlf=false -C $project archive --format=zip --prefix=Nebulah-Link/ --output=$output HEAD -- $paths
if ($LASTEXITCODE -ne 0) {
  if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output }
  throw 'Could not archive the beta commit.'
}
Write-Host "Archive: $output"
Write-Host "Files: $($paths.Count)"
Write-Host "SHA-256: $((Get-FileHash -Algorithm SHA256 -LiteralPath $output).Hash)"
if ($Preview) { Write-Host 'Preview only: archives committed HEAD; uncommitted changes are excluded.' }
