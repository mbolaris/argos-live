[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ConfirmedSerial,
  [Parameter(Mandatory)][UInt64]$ConfirmedCapacityBytes,
  [Parameter(Mandatory)][string]$ConfirmedUniqueId,
  [Parameter(Mandatory)][string]$ExpectedIsoSHA256
)
# Interactive local workflow, only after explicit owner approval of erasure.
# Passphrases go directly to cryptsetup's terminal; never use a transcript.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$status = Join-Path $root 'local-usb-write-status.json'
$image = Join-Path $root 'artifacts/argos-live-personal.raw'
function Set-Stage([string]$stage, [string]$detail='') {
  @{stage=$stage; detail=$detail; updated=(Get-Date).ToString('o')} |
    ConvertTo-Json | Set-Content -LiteralPath $status
}
try {
  $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator access required.' }
  $iso = Join-Path $root 'artifacts/argos-live-amd64.iso'
  if ((Get-FileHash $iso -Algorithm SHA256).Hash -ine $ExpectedIsoSHA256) { throw 'Generic image hash changed.' }
  $matches = @(Get-Disk | Where-Object { $_.BusType -eq 'USB' -and $_.SerialNumber.Trim() -eq $ConfirmedSerial -and $_.Size -eq $ConfirmedCapacityBytes -and $_.UniqueId -eq $ConfirmedUniqueId })
  if ($matches.Count -ne 1 -or $matches[0].IsBoot -or $matches[0].IsSystem -or $matches[0].IsReadOnly) { throw 'Approved USB missing or protected.' }
  if (Test-Path -LiteralPath $image) { throw 'Personal image already exists; inspect it before retrying.' }
  $wslRoot = (& wsl -d Ubuntu-26.04 -u root -- wslpath -a $root).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $wslRoot.StartsWith('/mnt/')) { throw 'Unable to resolve build directory in WSL.' }
  Set-Stage 'preparing-encrypted-image' 'Enter the new passphrase only in this local window.'
  Write-Host 'Create encrypted persistence: type YES when cryptsetup asks, then enter and verify your new passphrase. Enter it again to initialize the filesystem.'
  Write-Host 'Do not paste the passphrase into chat. Keep it: it will be required on every boot.'
  & wsl -d Ubuntu-26.04 -u root -- bash "$wslRoot/scripts/make-vm-image.sh" "$wslRoot/artifacts/argos-live-amd64.iso" "$wslRoot/artifacts/argos-live-personal.raw" "$ConfirmedCapacityBytes"
  if ($LASTEXITCODE -ne 0) { throw 'Encrypted image preparation failed; USB has not been written.' }
  $hash = ((Get-Content -LiteralPath "$image.sha256") -split '\s+')[0]
  if ($hash -notmatch '^[a-fA-F0-9]{64}$') { throw 'Personal image checksum missing.' }
  Set-Stage 'writing-and-verifying' 'Approved physical identity is rechecked by the writer immediately before opening the device.'
  & "$PSScriptRoot/write-usb.ps1" -Image $image -ExpectedSHA256 $hash -ConfirmedSerial $ConfirmedSerial -ConfirmedCapacityBytes $ConfirmedCapacityBytes -ConfirmedUniqueId $ConfirmedUniqueId -OwnerErasureConfirmed -Confirm:$false |
    Tee-Object -FilePath (Join-Path $root 'local-usb-write.log')
  Set-Stage 'complete' "Full image write and read-back SHA256 passed: $hash"
  Write-Host 'USB write verified. Keep this window open until Codex records the result.'
} catch {
  Set-Stage 'failed' $_.Exception.Message
  Write-Error $_ -ErrorAction Continue
}
