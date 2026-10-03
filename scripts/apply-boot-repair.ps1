[CmdletBinding()]
param([Parameter(Mandatory)][string]$Plan)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$status=Join-Path $root 'local/usb-boot-repair-status.json'
$handles=[Collections.Generic.List[Microsoft.Win32.SafeHandles.SafeFileHandle]]::new()
$device=$null
function Record([string]$stage,[string]$detail){@{stage=$stage;detail=$detail;updated=(Get-Date).ToString('o')}|ConvertTo-Json|Set-Content $status}
try {
  $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
  if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator access required.'}
  $repair=Get-Content -LiteralPath $Plan -Raw|ConvertFrom-Json
  function Identify {
    $matches=@(Get-Disk|Where-Object {$_.BusType -eq 'USB' -and $_.SerialNumber.Trim() -eq $repair.serial -and $_.Size -eq $repair.capacity -and $_.UniqueId -eq $repair.uniqueId})
    if($matches.Count -ne 1 -or $matches[0].IsBoot -or $matches[0].IsSystem -or $matches[0].IsReadOnly){throw 'Expected Kingston identity missing or protected.'}
    return $matches[0]
  }
  $disk=Identify
  if($repair.segments.Count -notin @(2,3)){throw 'Expected two menu patches or three access/menu patches.'}
  foreach($s in $repair.segments){
    if($s.offset -lt 1048576 -or $s.offset%512 -or $s.length%512 -or $s.length -gt 65536 -or $s.offset+$s.length -ge $repair.persistenceStart){throw 'Patch outside bounded boot-file region.'}
    if([Convert]::FromBase64String($s.before).Length -ne $s.length -or [Convert]::FromBase64String($s.after).Length -ne $s.length){throw 'Patch size mismatch.'}
  }
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class ArgosBootRepairIo {
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] public static extern SafeFileHandle CreateFile(string name,uint access,uint share,IntPtr security,uint creation,uint flags,IntPtr template);
 [DllImport("kernel32.dll",SetLastError=true)] public static extern bool DeviceIoControl(SafeFileHandle h,uint code,IntPtr input,uint ilen,IntPtr output,uint olen,out uint returned,IntPtr overlap);
 [DllImport("kernel32.dll",SetLastError=true)] public static extern bool ReadFile(SafeFileHandle h,byte[] buffer,uint count,out uint read,IntPtr overlap);
 [DllImport("kernel32.dll",SetLastError=true)] public static extern bool WriteFile(SafeFileHandle h,byte[] buffer,uint count,out uint written,IntPtr overlap);
 [DllImport("kernel32.dll",SetLastError=true)] public static extern bool SetFilePointerEx(SafeFileHandle h,long distance,out long position,uint method);
 [DllImport("kernel32.dll",SetLastError=true)] public static extern bool FlushFileBuffers(SafeFileHandle h);
}
'@
  foreach($path in @(Get-Partition -DiskNumber $disk.Number|ForEach-Object AccessPaths|Where-Object {$_ -like '\\?\Volume{*'}|Select-Object -Unique)){
    $h=[ArgosBootRepairIo]::CreateFile($path.TrimEnd([char]92),[uint32]3221225472,3,[IntPtr]::Zero,3,0,[IntPtr]::Zero)
    if($h.IsInvalid){throw 'Cannot open target volume.'};$handles.Add($h)
    [uint32]$returned=0
    foreach($code in @(0x00090018,0x00090020)){if(-not [ArgosBootRepairIo]::DeviceIoControl($h,$code,[IntPtr]::Zero,0,[IntPtr]::Zero,0,[ref]$returned,[IntPtr]::Zero)){throw 'Target volume lock/dismount failed; no patch started.'}}
  }
  $disk=Identify
  $device=[ArgosBootRepairIo]::CreateFile("\\.\PhysicalDrive$($disk.Number)",[uint32]3221225472,3,[IntPtr]::Zero,3,[uint32]2147483648,[IntPtr]::Zero)
  if($device.IsInvalid){throw 'Cannot open approved physical device.'}
  function Read-Bytes([long]$offset,[int]$length){
    [long]$position=0;[uint32]$count=0;$buffer=[byte[]]::new($length)
    if(-not [ArgosBootRepairIo]::SetFilePointerEx($device,$offset,[ref]$position,0)){throw 'Seek failed.'}
    if(-not [ArgosBootRepairIo]::ReadFile($device,$buffer,[uint32]$length,[ref]$count,[IntPtr]::Zero) -or $count -ne $length){throw 'Read failed.'}
    return ,$buffer
  }
  function Fingerprint([byte[]]$bytes){return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))}
  $gpt=Read-Bytes 512 512
  if([Text.Encoding]::ASCII.GetString($gpt,0,8) -ne 'EFI PART'){throw 'GPT signature missing.'}
  $tableLba=[BitConverter]::ToUInt64($gpt,72)
  $entryCount=[BitConverter]::ToUInt32($gpt,80)
  $entrySize=[BitConverter]::ToUInt32($gpt,84)
  if($entrySize -ne 128 -or $entryCount -lt 4 -or $entryCount -gt 4096 -or $tableLba*512+$entryCount*$entrySize -gt 1048576){throw 'Unsupported GPT entry geometry.'}
  $table=Read-Bytes ([long]$tableLba*512) ([int]$entryCount*$entrySize)
  $start=[BitConverter]::ToUInt64($table,3*$entrySize+32)*512
  if($start -ne $repair.persistenceStart){throw 'Encrypted persistence boundary changed.'}
  $protected=@(@{offset=0;length=1048576},@{offset=[long]$repair.capacity-1048576;length=1048576},@{offset=[long]$start;length=16777216})
  foreach($region in $protected){$region.hash=Fingerprint (Read-Bytes $region.offset $region.length)}
  foreach($s in $repair.segments){
    if((Fingerprint (Read-Bytes $s.offset $s.length)) -ne (Fingerprint ([Convert]::FromBase64String($s.before)))){throw 'Boot-file preimage differs; refuse patch.'}
  }
  Copy-Item -LiteralPath $Plan -Destination (Join-Path $root ("local/usb-boot-repair-backup-"+(Get-Date -Format yyyyMMdd-HHmmss)+".json"))
  Record 'patching' 'Changing only planned boot-region files and their checksum entries.'
  foreach($s in $repair.segments){
    [long]$position=0;[uint32]$count=0;$bytes=[Convert]::FromBase64String($s.after)
    if(-not [ArgosBootRepairIo]::SetFilePointerEx($device,[long]$s.offset,[ref]$position,0)){throw 'Patch seek failed.'}
    if(-not [ArgosBootRepairIo]::WriteFile($device,$bytes,[uint32]$bytes.Length,[ref]$count,[IntPtr]::Zero) -or $count -ne $bytes.Length){throw 'Patch write failed.'}
  }
  if(-not [ArgosBootRepairIo]::FlushFileBuffers($device)){throw 'Patch flush failed.'}
  foreach($s in $repair.segments){if((Fingerprint (Read-Bytes $s.offset $s.length)) -ne (Fingerprint ([Convert]::FromBase64String($s.after)))){throw 'Patch read-back mismatch.'}}
  foreach($region in $protected){if((Fingerprint (Read-Bytes $region.offset $region.length)) -ne $region.hash){throw 'Protected GPT/encryption header changed.'}}
  Record 'complete' 'All planned boot-file patches read back correctly. GPT copies and first 16 MiB of encrypted persistence unchanged; no writes entered persistence.'
  Write-Host 'Boot menu repair verified. Persistence and passphrase preserved.'
} catch {Record 'failed' $_.Exception.Message;Write-Error $_ -ErrorAction Continue}
finally {if($device){$device.Dispose()};foreach($h in $handles){$h.Dispose()}}
