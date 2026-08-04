param([string]$Config = "config/app.example.ini", [string]$BuildConfig = "Debug")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$serverStorage = Join-Path $root "runtime/server_storage"
$clientDownloads = Join-Path $root "runtime/client_downloads"
$serverExe = Join-Path $root "build/bin/$BuildConfig/HcmusSocketServer.exe"
$clientExe = Join-Path $root "build/bin/$BuildConfig/HcmusSocketClient.exe"
$configPath = Join-Path $root $Config
New-Item -ItemType Directory -Force $serverStorage, $clientDownloads | Out-Null
$cases = @(
    @{ Name = "small-512.bin"; Size = 512 },
    @{ Name = "medium-10MiB.bin"; Size = 10MB },
    @{ Name = "large-101MiB.bin"; Size = 101MB }
)
foreach ($case in $cases) {
    $source = Join-Path $serverStorage $case.Name
    $target = Join-Path $clientDownloads $case.Name
    Remove-Item -LiteralPath $source, $target, "$target.part" -Force -ErrorAction SilentlyContinue
    fsutil file createnew $source $case.Size | Out-Null
}
$server = Start-Process -FilePath $serverExe -ArgumentList "`"$configPath`"" -PassThru -WindowStyle Hidden
try {
    Start-Sleep -Milliseconds 500
    $commands = ($cases | ForEach-Object { "DOWNLOAD $($_.Name)" }) + "QUIT"
    $commands -join "`n" | & $clientExe $configPath
} finally { Stop-Process -Id $server.Id -ErrorAction SilentlyContinue }
$results = foreach ($case in $cases) {
    $sourceHash = (Get-FileHash (Join-Path $serverStorage $case.Name) -Algorithm SHA256).Hash
    $targetHash = (Get-FileHash (Join-Path $clientDownloads $case.Name) -Algorithm SHA256).Hash
    [pscustomobject]@{ File=$case.Name; Bytes=$case.Size; SHA256=$targetHash; Match=($sourceHash -eq $targetHash) }
}
$results | Format-Table -AutoSize
Write-Host "Transfer timing and KB/s: $serverStorage/server.log"
