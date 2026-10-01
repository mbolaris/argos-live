[CmdletBinding(SupportsShouldProcess, ConfirmImpact='High')]
param(
  [Parameter(Mandatory)][string]$Image,
  [Parameter(Mandatory)][string]$ExpectedSHA256,
  [Parameter(Mandatory)][string]$ConfirmedSerial,
  [Parameter(Mandatory)][UInt64]$ConfirmedCapacityBytes,
  [Parameter(Mandatory)][string]$ConfirmedUniqueId
)
# Run only AFTER the owner approves the reviewed device and erasure.
# No disk selection by letter or remembered number. All mounted target volumes
# must lock and dismount successfully before raw writes can begin.
$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this reviewed script in an elevated local PowerShell session.' }
$file = Get-Item -LiteralPath $Image
if ($file.Name -like '*TEST-DO-NOT-WRITE*') { throw 'Disposable test VM images must never be written to physical media.' }
if ($file.PSIsContainer -or $file.Length % 512 -ne 0) { throw 'A sector-aligned regular image file is required.' }
if ((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ine $ExpectedSHA256) { throw 'Image hash mismatch.' }
function Find-ApprovedDevice {
  $matches = @(Get-Disk | Where-Object { $_.BusType -eq 'USB' -and $_.SerialNumber.Trim() -eq $ConfirmedSerial -and $_.Size -eq $ConfirmedCapacityBytes -and $_.UniqueId -eq $ConfirmedUniqueId })
  if ($matches.Count -ne 1) { throw 'Approved physical identity is missing or ambiguous.' }
  if ($matches[0].IsBoot -or $matches[0].IsSystem -or $matches[0].IsReadOnly) { throw 'Protected target rejected.' }
  return $matches[0]
}
$disk = Find-ApprovedDevice
if ($file.Length -gt $disk.Size) { throw 'Image exceeds target capacity.' }
$parts = @(Get-Partition -DiskNumber $disk.Number)
if (@($parts | ForEach-Object { [string]$_.DriveLetter }) -contains $file.PSDrive.Name) { throw 'Source image is on the target device.' }
$disk | Format-List FriendlyName,SerialNumber,UniqueId,BusType,Size
$parts | Format-Table PartitionNumber,DriveLetter,Type,Offset,Size
Write-Host 'Writing this image erases ALL existing contents and partitions on the displayed USB.'
if (-not $PSCmdlet.ShouldProcess($disk.UniqueId, "Erase whole USB and write $($file.FullName) [$ExpectedSHA256]")) { return }
if ((Read-Host "Type ERASE $ConfirmedSerial to confirm this target and its erasure") -cne "ERASE $ConfirmedSerial") { throw 'Erasure not confirmed.' }
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class ArgosDeviceIo {
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool DeviceIoControl(SafeFileHandle h, uint code, IntPtr input, uint ilen, IntPtr output, uint olen, out uint returned, IntPtr overlap);
}
'@
$handles = [Collections.Generic.List[Microsoft.Win32.SafeHandles.SafeFileHandle]]::new()
$device = $null
$input = $null
try {
  foreach ($path in @($parts | ForEach-Object AccessPaths | Where-Object { $_ -like '\\?\Volume{*' } | Select-Object -Unique)) {
    $h = [ArgosDeviceIo]::CreateFile($path.TrimEnd([char]92), 0xC0000000, 3, [IntPtr]::Zero, 3, 0, [IntPtr]::Zero)
    if ($h.IsInvalid) { throw "Cannot open target volume for exclusive lock: $path" }
    $handles.Add($h)
    [uint32]$returned = 0
    foreach ($code in @(0x00090018, 0x00090020)) {
      if (-not [ArgosDeviceIo]::DeviceIoControl($h, $code, [IntPtr]::Zero, 0, [IntPtr]::Zero, 0, [ref]$returned, [IntPtr]::Zero)) { throw 'Volume lock or dismount failed; no raw write started.' }
    }
  }
  # Immediate final identity check after any volume operation.
  $disk = Find-ApprovedDevice
  $device = [IO.FileStream]::new("\\.\PhysicalDrive$($disk.Number)", [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite, 1048576, [IO.FileOptions]::WriteThrough)
  $input = [IO.File]::OpenRead($file.FullName)
  $buffer = [byte[]]::new(4MB)
  [Int64]$written = 0
  while (($count = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
    $device.Write($buffer, 0, $count)
    $written += $count
    Write-Progress -Activity 'Writing approved Argos USB' -PercentComplete (100 * $written / $file.Length)
  }
  $device.Flush($true)
  $device.Position = 0
  $sha = [Security.Cryptography.SHA256]::Create()
  [Int64]$remaining = $file.Length
  while ($remaining -gt 0) {
    $count = $device.Read($buffer, 0, [int][Math]::Min($buffer.Length, $remaining))
    if ($count -le 0) { throw 'USB read-back ended early.' }
    [void]$sha.TransformBlock($buffer, 0, $count, $buffer, 0)
    $remaining -= $count
  }
  [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
  $actual = [BitConverter]::ToString($sha.Hash).Replace('-', '')
  $sha.Dispose()
  if ($actual -ine $ExpectedSHA256) { throw 'USB read-back checksum failed. Treat this media as unusable.' }
  Write-Host "Write and read-back verification passed: $actual. Safely eject before booting."
} finally {
  if ($input) { $input.Dispose() }
  if ($device) { $device.Dispose() }
  foreach ($h in $handles) { $h.Dispose() }
}
