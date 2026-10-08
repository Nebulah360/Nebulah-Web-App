param([switch]$Preview, [string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$git = @(git -c "safe.directory=$project" -C $project status --porcelain)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect repository state.' }
if ($git.Count -and -not $Preview) { throw 'Commit the tested build before making a standalone release. Use -Preview for local trials.' }
$commit = (git -c "safe.directory=$project" -C $project rev-parse --short=12 HEAD).Trim()
$label = if ($Preview) { "$commit-preview" } else { $commit }
$outputParent = Join-Path $project ".local\releases\standalone-$label"
if (Test-Path -LiteralPath $outputParent) { throw "Standalone build already exists: $outputParent" }
$buildRoot = Join-Path $project ('.local\standalone-build\' + [guid]::NewGuid().ToString('N'))
$stage = Join-Path $buildRoot 'assets'
$work = Join-Path $buildRoot 'work'
$pyInstallerVersion = & $Python -m PyInstaller --version 2>$null
if ($LASTEXITCODE -ne 0 -or "$pyInstallerVersion".Trim() -ne '6.22.3') {
  throw 'PyInstaller 6.22.3 is required only on the build PC. Install pyinstaller==6.22.3 in a build environment.'
}
try {
  $paths = @(git -c "safe.directory=$project" -C $project ls-files --cached -- bridge dist registry support tools README.md 'Allow Phone Through Firewall.cmd')
  if ($LASTEXITCODE -ne 0) { throw 'Cannot list standalone assets.' }
  $assets = @($paths | Where-Object {
    $_ -match '^bridge/[^/]+\.(ps1|cs)$|^dist/|^registry/|^support/|^tools/[^/]+\.ps1$|^(README\.md|Allow Phone Through Firewall\.cmd)$' -and
    ($_ -eq 'README.md' -or $_ -notmatch '(^|/)README\.md$')
  })
  foreach ($path in $assets) {
    $source = Join-Path $project $path
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing standalone asset: $path" }
    $target = Join-Path $stage $path
    [IO.Directory]::CreateDirectory((Split-Path $target)) | Out-Null
    Copy-Item -LiteralPath $source -Destination $target
  }
  $data = @()
  foreach ($folder in @('bridge','dist','registry','support','tools')) {
    $data += @('--add-data', "$(Join-Path $stage $folder);$folder")
  }
  foreach ($file in @('README.md','Allow Phone Through Firewall.cmd')) {
    $data += @('--add-data', "$(Join-Path $stage $file);.")
  }
  & $Python -m PyInstaller --onedir --contents-directory . --name Nebulah-Link `
    --distpath $outputParent --workpath $work --specpath $buildRoot `
    --paths (Join-Path $project 'bridge') @data (Join-Path $project 'tools\standalone.py')
  if ($LASTEXITCODE -ne 0) { throw 'Standalone build failed.' }
  $exe = Join-Path $outputParent 'Nebulah-Link\Nebulah-Link.exe'
  if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Standalone executable is missing.' }
  Write-Host "Standalone folder: $(Split-Path $exe)"
  Write-Host "Executable SHA-256: $((Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash)"
} finally {
  $resolved = [IO.Path]::GetFullPath($buildRoot)
  $allowed = [IO.Path]::GetFullPath((Join-Path $project '.local\standalone-build')) + [IO.Path]::DirectorySeparatorChar
  if ($resolved.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolved)) {
    Remove-Item -LiteralPath $resolved -Recurse -Force
  }
}
