[CmdletBinding()]
param(
    [string]$TargetPath = (Join-Path $env:USERPROFILE "AI-Assistant"),
    [switch]$RunTests
)

$installer = Join-Path (
    Split-Path -Parent $MyInvocation.MyCommand.Path
) "INSTALL_STABLE_V1.ps1"

& $installer -TargetPath $TargetPath -RunTests:$RunTests
