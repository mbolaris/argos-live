[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Image,
  [Parameter(Mandatory)][string]$ExpectedSHA256,
  [Parameter(Mandatory)][string]$ConfirmedSerial,
  [Parameter(Mandatory)][UInt64]$ConfirmedCapacityBytes,
  [Parameter(Mandatory)][string]$ConfirmedUniqueId
)
# Reuses a completed encrypted image; never recreates encryption or requests keys.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$status = Join-Path $root 'local-usb-write-status.json'
try {
  @{stage='writing-and-verifying'; detail='Image hash and approved USB identity are checked before writing.'; updated=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content $status
  & "$PSScriptRoot/write-usb.ps1" -Image $Image -ExpectedSHA256 $ExpectedSHA256 -ConfirmedSerial $ConfirmedSerial -ConfirmedCapacityBytes $ConfirmedCapacityBytes -ConfirmedUniqueId $ConfirmedUniqueId -OwnerErasureConfirmed -Confirm:$false |
    Tee-Object -FilePath (Join-Path $root 'local-usb-write.log')
  @{stage='complete'; detail="Full USB write and read-back SHA256 passed: $ExpectedSHA256"; updated=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content $status
} catch {
  @{stage='failed'; detail=$_.Exception.Message; updated=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content $status
  Write-Error $_ -ErrorAction Continue
}
