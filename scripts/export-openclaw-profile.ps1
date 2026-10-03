[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][string]$OutputDirectory,
 [string]$WslDistro,
 [string]$OpenClawCommand='openclaw'
)
$ErrorActionPreference='Stop'
# Native OpenClaw backups include private state. Use protected local storage,
# not a public checkout, model/data volume or downloadable public URL.
$parent=(Resolve-Path -LiteralPath $OutputDirectory).Path
$privateDir=Join-Path $parent ('profile-'+(Get-Date -Format 'yyyyMMdd-HHmmssfff'))
if (Test-Path -LiteralPath $privateDir) { throw 'Export directory already exists; refuse overwrite.' }
New-Item -ItemType Directory -Path $privateDir | Out-Null
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$ownerGrant='*'+$identity.User.Value+':(OI)(CI)F'
& icacls.exe $privateDir /inheritance:r /grant:r $ownerGrant '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Private export directory ACL could not be restricted.' }
$archive=Join-Path $privateDir 'openclaw-profile.tar.gz'
$log=Join-Path $privateDir 'export.log'
function Invoke-OpenClaw([string[]]$CliArguments) {
 $previous=$ErrorActionPreference
 try {
 $ErrorActionPreference='Continue'
 if ($WslDistro) { $result=& wsl.exe --distribution $WslDistro --exec $OpenClawCommand @CliArguments 2>&1 }
 else { $result=& $OpenClawCommand @CliArguments 2>&1 }
 $code=$LASTEXITCODE
 } finally { $ErrorActionPreference=$previous }
 $result | Out-String | Add-Content -LiteralPath $log -Encoding UTF8
 if ($code -ne 0) { throw "OpenClaw command failed; inspect the private export log. Exit=$code" }
}
$targetArchive=$archive
if ($WslDistro) {
 $converted=& wsl.exe --distribution $WslDistro --exec wslpath -u $archive
 if ($LASTEXITCODE -ne 0 -or -not $converted) { throw 'Cannot translate the private output path for WSL.' }
 $targetArchive=($converted | Out-String).Trim()
}
Invoke-OpenClaw -CliArguments @('--version')
Invoke-OpenClaw -CliArguments @('agents','list','--json')
Invoke-OpenClaw -CliArguments @('backup','create','--output',$targetArchive,'--verify')
if (-not (Test-Path -LiteralPath $archive)) { throw 'Verified backup archive was not created.' }
$sha=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
@{created=(Get-Date).ToString('o');archive='openclaw-profile.tar.gz';sha256=$sha;bytes=(Get-Item -LiteralPath $archive).Length;sourceKind=$(if ($WslDistro) {'WSL'} else {'Windows'});privateState=$true;verifiedBy='openclaw backup create --verify'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $privateDir 'export-result.json') -Encoding UTF8
Write-Host "Private verified export: $archive"
Write-Host "SHA256: $sha"
Write-Host 'No source configuration changed. Transfer privately; activate only after staged path/schema review.'
