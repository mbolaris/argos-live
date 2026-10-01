[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
[ordered]@{
  computer = $env:COMPUTERNAME
  administrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  disks = @(Get-Disk | Select-Object Number,FriendlyName,SerialNumber,UniqueId,BusType,Size,PartitionStyle,IsBoot,IsSystem,IsReadOnly)
  partitions = @(Get-Partition | Select-Object DiskNumber,PartitionNumber,DriveLetter,Offset,Size,Type)
  volumes = @(Get-Volume | Select-Object DriveLetter,FileSystemLabel,FileSystem,Size,SizeRemaining)
} | ConvertTo-Json -Depth 5
