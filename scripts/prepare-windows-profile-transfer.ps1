param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [Parameter(Mandatory=$true)][string]$Account,
    [Parameter(Mandatory=$true)][string]$PublicKey,
    [Parameter(Mandatory=$true)][string]$ControllerIP,
    [Parameter(Mandatory=$true)][string]$ListenIP,
    [int]$Port = 2222
)
# Prepares a private, read-only SFTP candidate. Does not activate services/firewall.
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run through the local implementing agent with administrator rights.' }
if ($Account -notmatch '^[a-zA-Z0-9_.-]+$') { throw 'Use an inspected local Windows account name; do not guess or create one.' }
$localAccount = Get-LocalUser -Name $Account
if (-not $localAccount.Enabled) { throw 'Selected account is disabled.' }
foreach ($address in @($ControllerIP,$ListenIP)) {
    if ($address -notmatch '^192\.168\.1\.(\d{1,3})$' -or [int]$Matches[1] -lt 2 -or [int]$Matches[1] -gt 254) { throw 'Expected a verified trusted 192.168.1.x LAN address.' }
}
if ($ControllerIP -eq $ListenIP) { throw 'Controller and source must be different machines.' }
if (-not (Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -eq $ListenIP)) { throw 'Listen address is not currently assigned here.' }
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Use an unused high port for the temporary endpoint.' }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { throw 'Selected port already has a listener; preserve it.' }
$source = Get-Item -LiteralPath $Archive
if ($source.PSIsContainer -or $source.Extension -ne '.zip' -or ($source.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Expected an existing regular private ZIP.' }
$drive = [IO.Path]::GetPathRoot($source.FullName).TrimEnd('\')
$protection = Get-BitLockerVolume -MountPoint $drive
if ([string]$protection.ProtectionStatus -ne 'On') { throw 'Source export must remain on protected BitLocker storage.' }
$systemProtection = Get-BitLockerVolume -MountPoint $env:SystemDrive
if ([string]$systemProtection.ProtectionStatus -ne 'On') { throw 'Temporary staging requires protected system storage.' }
$keyText = (Get-Content -LiteralPath $PublicKey -Raw).Trim()
if ($keyText -notmatch '^ssh-ed25519 [A-Za-z0-9+/]+={0,3}( [^\r\n]*)?$') { throw 'Expected one Ed25519 public key, never a private key.' }
$sshRoot = Join-Path $env:WINDIR 'System32\OpenSSH'
$sshd = Join-Path $sshRoot 'sshd.exe'
$keygen = Join-Path $sshRoot 'ssh-keygen.exe'
if (-not (Test-Path -LiteralPath $sshd) -or -not (Test-Path -LiteralPath $keygen)) { throw 'Local agent must inspect/install the Windows OpenSSH Server capability first; no services were changed.' }
$root = Join-Path $env:ProgramData ('ArgosProfileTransfer-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff'))
if (Test-Path -LiteralPath $root) { throw 'Use a fresh transfer directory.' }
New-Item -ItemType Directory -Path $root | Out-Null
& icacls.exe $root /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Private directory ACL setup failed.' }
$share = Join-Path $root 'share'
New-Item -ItemType Directory -Path $share | Out-Null
$accountGrant = '*' + $localAccount.SID.Value + ':(OI)(CI)RX'
& icacls.exe $share /grant:r $accountGrant | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Account read-only ACL setup failed.' }
Copy-Item -LiteralPath $source.FullName -Destination (Join-Path $share 'profile.zip')
$hash = (Get-FileHash -LiteralPath $source.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ((Get-FileHash -LiteralPath (Join-Path $share 'profile.zip') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash) { throw 'Private staging copy verification failed.' }
Set-Content -LiteralPath (Join-Path $root 'authorized_keys') -Encoding Ascii -Value ('restrict ' + $keyText)
$hostKey = Join-Path $root 'host_ed25519'
& $keygen -q -t ed25519 -N '""' -f $hostKey
if ($LASTEXITCODE -ne 0) { throw 'Dedicated host-key generation failed.' }
$config = @"
Port $Port
ListenAddress $ListenIP
HostKey "$($hostKey.Replace('\','/'))"
AuthorizedKeysFile "$((Join-Path $root 'authorized_keys').Replace('\','/'))"
AllowUsers $($Account.ToLowerInvariant())@$ControllerIP
PubkeyAuthentication yes
AuthenticationMethods publickey
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
AllowTcpForwarding no
AllowAgentForwarding no
PermitTunnel no
X11Forwarding no
PermitTTY no
Subsystem sftp internal-sftp
ChrootDirectory "$($share.Replace('\','/'))"
ForceCommand internal-sftp -R -d /
"@
$configPath = Join-Path $root 'sshd_config'
Set-Content -LiteralPath $configPath -Encoding Ascii -Value $config
& $sshd -t -f $configPath
if ($LASTEXITCODE -ne 0) { throw 'Candidate SSH configuration rejected; no service/firewall activated.' }
Write-Output "Prepared only: $root"
Write-Output "Archive SHA256: $hash"
Write-Output "Account: $Account; Endpoint: ${ListenIP}:$Port; Controller: $ControllerIP"
& $keygen -lf ($hostKey + '.pub') -E sha256
Write-Output 'Local agent must review ACLs/effective config, activate a temporary source-restricted endpoint, verify SFTP read-only/chroot behavior, and report the public host key. Do not reboot. Do not replace a working SSH service/configuration. Remove only this endpoint and its firewall rule after verified receipt.'
