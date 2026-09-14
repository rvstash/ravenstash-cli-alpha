[CmdletBinding()]
param(
    [ValidateSet("User", "Machine")][string]$Scope = "User",
    [string]$InstallRoot,
    [switch]$Repair
)

$ErrorActionPreference = "Stop"
$ReleaseVersion = "0.12.2"
$CompatibilityChannel = "v0.12"
$Repository = "rvstash/ravenstash-cli-alpha"
$ReleaseBase = "https://github.com/$Repository/releases/download/v$ReleaseVersion"

function Get-Architecture {
    switch ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()) {
        "X64" { "amd64" }
        "Arm64" { "arm64" }
        default { throw "Unsupported Windows architecture: $_" }
    }
}

function Invoke-ReleaseDownload([string]$Uri, [string]$OutFile) {
    $headers = @{}
    if ($env:RVS_GITHUB_TOKEN) {
        $headers.Authorization = "Bearer $($env:RVS_GITHUB_TOKEN)"
        $headers.Accept = "application/octet-stream"
        $assetName = Split-Path -Leaf $Uri
        $release = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$Repository/releases/tags/v$ReleaseVersion"
        $asset = $release.assets | Where-Object name -eq $assetName | Select-Object -First 1
        if (-not $asset) { throw "Release v$ReleaseVersion does not contain $assetName" }
        Invoke-WebRequest -Headers $headers -Uri $asset.url -OutFile $OutFile
        return
    }
    Invoke-WebRequest -Uri $Uri -OutFile $OutFile
}

$architecture = Get-Architecture
$archiveName = "rvs-v$ReleaseVersion-windows-$architecture.zip"
$checksumsName = "rvs-v$ReleaseVersion-checksums.txt"
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("rvs-install-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $archive = Join-Path $temporary $archiveName
    $checksums = Join-Path $temporary $checksumsName
    Invoke-ReleaseDownload "$ReleaseBase/$archiveName" $archive
    Invoke-ReleaseDownload "$ReleaseBase/$checksumsName" $checksums
    $line = Get-Content $checksums | Where-Object { $_ -match "  $([regex]::Escape($archiveName))$" } | Select-Object -First 1
    if (-not $line) { throw "Release checksum inventory does not contain $archiveName" }
    $expected = ($line -split '\s+')[0].ToLowerInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "SHA-256 mismatch for $archiveName" }

    Expand-Archive -LiteralPath $archive -DestinationPath $temporary
    $source = Join-Path $temporary "rvs-v$ReleaseVersion-windows-$architecture"
    foreach ($launcherName in @("rvs.exe", "ravenstash.exe", "docker-credential-rvs.exe")) {
        $launcher = Join-Path $source $launcherName
        if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
            throw "Archive is missing $launcherName"
        }
    }

    if (-not $InstallRoot) {
        $InstallRoot = if ($Scope -eq "Machine") {
            Join-Path $env:ProgramFiles "Ravenstash\rvs"
        } else {
            Join-Path $env:LOCALAPPDATA "Ravenstash\rvs"
        }
    }
    $bin = Join-Path $InstallRoot "bin"
    if ((Test-Path $bin) -and -not $Repair) {
        $installed = & (Join-Path $bin "rvs.exe") --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $installed -match $ReleaseVersion) {
            Write-Host "rvs $ReleaseVersion is already installed at $bin"
            exit 0
        }
    }
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    $staged = Join-Path $InstallRoot (".staged-" + [guid]::NewGuid())
    Copy-Item -Recurse -LiteralPath $source -Destination $staged
    if (Test-Path $bin) { Remove-Item -Recurse -Force -LiteralPath $bin }
    Move-Item -LiteralPath $staged -Destination $bin
    Set-Content -LiteralPath (Join-Path $InstallRoot "channel") -Value $CompatibilityChannel -Encoding ascii

    $pathTarget = if ($Scope -eq "Machine") { "Machine" } else { "User" }
    $currentPath = [Environment]::GetEnvironmentVariable("Path", $pathTarget)
    $entries = @($currentPath -split ';' | Where-Object { $_ -and $_ -ne $bin })
    [Environment]::SetEnvironmentVariable("Path", (($entries + $bin) -join ';'), $pathTarget)
    $env:Path = "$bin;$env:Path"
    & (Join-Path $bin "rvs.exe") --version
    Write-Host "Installed rvs $ReleaseVersion on compatibility channel $CompatibilityChannel"
    Write-Host "Open a new terminal, then run: rvs auth login"
}
finally {
    if (Test-Path $temporary) { Remove-Item -Recurse -Force -LiteralPath $temporary }
}
