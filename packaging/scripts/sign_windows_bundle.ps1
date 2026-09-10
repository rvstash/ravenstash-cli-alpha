$ErrorActionPreference = "Stop"
if (-not $env:RVS_CODESIGN_PFX_BASE64 -or -not $env:RVS_CODESIGN_PASSWORD) {
    throw "The code-signing environment must provide RVS_CODESIGN_PFX_BASE64 and RVS_CODESIGN_PASSWORD"
}

$archive = Get-ChildItem "dist/release/rvs-v*-windows-*.zip" | Select-Object -First 1
if (-not $archive) { throw "Windows release archive was not built" }
$temporary = Join-Path $env:RUNNER_TEMP ("rvs-sign-" + [guid]::NewGuid())
$certificate = Join-Path $temporary "codesign.pfx"
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    [IO.File]::WriteAllBytes($certificate, [Convert]::FromBase64String($env:RVS_CODESIGN_PFX_BASE64))
    Expand-Archive -LiteralPath $archive.FullName -DestinationPath $temporary
    $signTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\*\signtool.exe" |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signTool) { throw "signtool.exe was not found" }
    $launchers = Get-ChildItem $temporary -Recurse -File |
        Where-Object Name -in @("rvs.exe", "ravenstash.exe", "docker-credential-rvs.exe")
    if ($launchers.Count -ne 3) { throw "Expected exactly three Windows launchers" }
    foreach ($launcher in $launchers) {
        & $signTool.FullName sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com `
            /f $certificate /p $env:RVS_CODESIGN_PASSWORD $launcher.FullName
        if ($LASTEXITCODE -ne 0) { throw "signtool failed for $($launcher.Name)" }
        & $signTool.FullName verify /pa /all $launcher.FullName
        if ($LASTEXITCODE -ne 0) { throw "Authenticode verification failed for $($launcher.Name)" }
    }
    Remove-Item -LiteralPath $archive.FullName
    $root = Get-ChildItem $temporary -Directory | Select-Object -First 1
    Compress-Archive -Path $root.FullName -DestinationPath $archive.FullName -CompressionLevel Optimal
}
finally {
    if (Test-Path $temporary) { Remove-Item -Recurse -Force -LiteralPath $temporary }
}
