[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Image,
  [Parameter(Mandatory)][string]$ExpectedSHA256,
  [string]$Serial = '0B8F640168E7',
  [UInt64]$CapacityBytes = 31474057216
)
# Read-only review. This script does NOT format, dismount, or write disks.
$ErrorActionPreference = 'Stop'
$file = Get-Item -LiteralPath $Image
if ($file.PSIsContainer) { throw 'Image must be a regular file.' }
$hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
if ($hash -ine $ExpectedSHA256) { throw 'Image checksum differs from approved artifact.' }
$candidates = @(Get-Disk | Where-Object { $_.BusType -eq 'USB' -and $_.SerialNumber.Trim() -eq $Serial -and $_.Size -eq $CapacityBytes })
if ($candidates.Count -ne 1) { throw 'Expected USB identity is missing or ambiguous.' }
$disk = $candidates[0]
if ($disk.IsBoot -or $disk.IsSystem -or $disk.IsReadOnly) { throw 'Target is protected, boot/system, or read-only.' }
if ($file.Length -gt $disk.Size) { throw 'Image exceeds USB capacity.' }
$partitionLetters = @(Get-Partition -DiskNumber $disk.Number | Where-Object DriveLetter | ForEach-Object { [string]$_.DriveLetter })
if ($partitionLetters -contains $file.PSDrive.Name) { throw 'Source image is stored on the target device.' }
[ordered]@{
  action = 'PENDING OWNER CONFIRMATION: erase this whole USB and write the verified full-disk image'
  image = $file.FullName
  imageBytes = $file.Length
  sha256 = $hash
  physicalPathForCurrentInventoryOnly = "\\.\PhysicalDrive$($disk.Number)"
  disk = $disk | Select-Object FriendlyName,SerialNumber,UniqueId,BusType,Size,IsBoot,IsSystem,IsReadOnly
  partitions = @(Get-Partition -DiskNumber $disk.Number | Select-Object PartitionNumber,DriveLetter,Offset,Size,Type)
  warning = 'ALL existing partitions and contents on this device will be erased. Recheck full identity immediately before writing. Windows elevation and exclusive access are required.'
} | ConvertTo-Json -Depth 5
