$ErrorActionPreference = 'Stop'
$disks = @(Get-Disk | Where-Object { $_.BusType -eq 'USB' })
$rows = @(foreach ($disk in $disks) {
    $volumes = @()
    try {
        $volumes = @(Get-Partition -DiskNumber $disk.Number -ErrorAction Stop |
            Get-Volume -ErrorAction Stop |
            Where-Object { $_.DriveLetter } |
            ForEach-Object {
                [pscustomobject]@{
                    letter = [string]$_.DriveLetter
                    label = [string]$_.FileSystemLabel
                    filesystem = [string]$_.FileSystem
                    bytes = [long]$_.Size
                    free_bytes = [long]$_.SizeRemaining
                    health = [string]$_.HealthStatus
                }
            })
    } catch {
        # A disk without a readable volume is still shown as a physical USB disk.
    }
    [pscustomobject]@{
        number = [int]$disk.Number
        model = [string]$disk.FriendlyName
        bytes = [long]$disk.Size
        partition_style = [string]$disk.PartitionStyle
        operational_status = [string]$disk.OperationalStatus
        system = [bool]$disk.IsSystem
        boot = [bool]$disk.IsBoot
        read_only = [bool]$disk.IsReadOnly
        volumes = $volumes
    }
})
ConvertTo-Json -InputObject $rows -Depth 5 -Compress
