[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath(
    (Split-Path -Parent $MyInvocation.MyCommand.Path)
)
$expectedBuild = "bekki-temporal-evidence-graceful-fallback-v1-10-51-11-20260904"

Push-Location $root
try {
    $metadata = Get-Content -Raw -Encoding UTF8 .\BEKKI_BUILD.json |
        ConvertFrom-Json
    if ($metadata.build_id -ne $expectedBuild) {
        throw "Unexpected build: $($metadata.build_id)"
    }

    python -m unittest tests.test_ui_font_consistency_hotfix_v1_10_50_1
    if ($LASTEXITCODE -ne 0) {
        throw "Font consistency regression test failed."
    }

    $rootUi = (Get-FileHash .\ui.py -Algorithm SHA256).Hash
    $runtimeUi = (Get-FileHash .\casper\ui.py -Algorithm SHA256).Hash
    $rootMarkdown = (Get-FileHash .\message_markdown.py -Algorithm SHA256).Hash
    $runtimeMarkdown = (
        Get-FileHash .\casper\message_markdown.py -Algorithm SHA256
    ).Hash

    Write-Output "build_id = $($metadata.build_id)"
    Write-Output "ui_mirror_match = $($rootUi -eq $runtimeUi)"
    Write-Output "markdown_mirror_match = $($rootMarkdown -eq $runtimeMarkdown)"
    Write-Output "startup_warning_expected = absent"
    Write-Output "visual_test_plain = 字体测试：四禧丸子的四位成员为沐霂、又一、梨安、恬豆；Chinese and English should stay even."
    Write-Output "visual_test_markdown = **这几个字应当加粗**，其余文字保持正常字重。"
} finally {
    Pop-Location
}
