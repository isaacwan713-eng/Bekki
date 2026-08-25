[CmdletBinding()]
param(
    [string]$TargetPath = (Join-Path $env:USERPROFILE "AI-Assistant"),
    [switch]$RunTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$sourceRoot = [IO.Path]::GetFullPath(
    (Split-Path -Parent $MyInvocation.MyCommand.Path)
)
$targetRoot = [IO.Path]::GetFullPath($TargetPath)

$rootTrimCharacters = [char[]]@(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
if (
    $sourceRoot.TrimEnd($rootTrimCharacters) -eq
    $targetRoot.TrimEnd($rootTrimCharacters)
) {
    throw "Extract Stable V1.3.9.5 outside the installed AI-Assistant folder."
}
if (-not (Test-Path (Join-Path $sourceRoot "main.py"))) {
    throw "Invalid Stable V1.3.9.5 package: main.py is missing."
}
if (-not (Test-Path (Join-Path $sourceRoot "BEKKI_BUILD.json"))) {
    throw "Invalid Stable V1.3.9.5 package: BEKKI_BUILD.json is missing."
}
if (Test-Path $targetRoot) {
    if (-not (Test-Path (Join-Path $targetRoot "main.py"))) {
        throw "Target exists but is not a Bekki source folder: $targetRoot"
    }
} else {
    New-Item -ItemType Directory -Path $targetRoot | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupRoot = Join-Path (Split-Path $targetRoot -Parent) (
    "_bekki_stable_v1_backup_" + $timestamp
)
New-Item -ItemType Directory -Path $backupRoot | Out-Null

$replaceDirectories = @("assets", "casper", "prompts", "tests")
$protectedNames = @(
    ".git", ".venv", "venv", "data", "build", "dist",
    "__pycache__", "casper_browser_profile", "logs"
)
$createdRootFiles = [System.Collections.Generic.List[string]]::new()
$backedUpRootFiles = [System.Collections.Generic.List[string]]::new()

function Get-CompatibleRelativePath(
    [string]$BasePath,
    [string]$ChildPath
) {
    $baseFullPath = [IO.Path]::GetFullPath($BasePath).TrimEnd(
        [char[]]@(
            [IO.Path]::DirectorySeparatorChar,
            [IO.Path]::AltDirectorySeparatorChar
        )
    )
    $childFullPath = [IO.Path]::GetFullPath($ChildPath)
    $prefix = $baseFullPath + [IO.Path]::DirectorySeparatorChar
    if (-not $childFullPath.StartsWith(
        $prefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Package file is outside the source folder: $ChildPath"
    }
    return $childFullPath.Substring($prefix.Length)
}

function Backup-Directory([string]$RelativePath) {
    $current = Join-Path $targetRoot $RelativePath
    if (-not (Test-Path $current)) {
        return
    }
    $backupParent = Split-Path (
        Join-Path $backupRoot $RelativePath
    ) -Parent
    New-Item -ItemType Directory -Force -Path $backupParent | Out-Null
    Copy-Item -LiteralPath $current -Destination $backupParent -Recurse -Force
}

function Restore-StableRuntime {
    foreach ($relative in $replaceDirectories) {
        $current = Join-Path $targetRoot $relative
        if (Test-Path $current) {
            Remove-Item -LiteralPath $current -Recurse -Force
        }
        $saved = Join-Path $backupRoot $relative
        if (Test-Path $saved) {
            Copy-Item -LiteralPath $saved -Destination $targetRoot -Recurse -Force
        }
    }
    foreach ($relative in $backedUpRootFiles) {
        $saved = Join-Path $backupRoot $relative
        $destination = Join-Path $targetRoot $relative
        if (Test-Path $saved) {
            Copy-Item -LiteralPath $saved -Destination $destination -Force
        }
    }
    foreach ($relative in $createdRootFiles) {
        $destination = Join-Path $targetRoot $relative
        if (Test-Path $destination) {
            Remove-Item -LiteralPath $destination -Force
        }
    }
}

try {
    foreach ($relative in $replaceDirectories) {
        Backup-Directory $relative
        $current = Join-Path $targetRoot $relative
        if (Test-Path $current) {
            Remove-Item -LiteralPath $current -Recurse -Force
        }
    }

    $sourceFiles = Get-ChildItem -LiteralPath $sourceRoot -File -Recurse
    foreach ($file in $sourceFiles) {
        $relative = Get-CompatibleRelativePath $sourceRoot $file.FullName
        $segments = $relative -split "[\\/]"
        if ($segments[0] -in $protectedNames) {
            continue
        }
        if (@($segments | Where-Object { $_ -in $protectedNames }).Count -gt 0) {
            continue
        }
        if (
            $file.Name -eq ".env" -or
            $file.Name -like ".env.*" -or
            $file.Extension -in @(".pyc", ".zip")
        ) {
            continue
        }

        $destination = Join-Path $targetRoot $relative
        $destinationParent = Split-Path $destination -Parent
        New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null

        if ($segments.Count -eq 1) {
            if (Test-Path $destination) {
                Copy-Item -LiteralPath $destination -Destination (
                    Join-Path $backupRoot $relative
                ) -Force
                $backedUpRootFiles.Add($relative)
            } else {
                $createdRootFiles.Add($relative)
            }
        }
        Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
    }

    $sourceBuild = Get-Content -LiteralPath (
        Join-Path $sourceRoot "BEKKI_BUILD.json"
    ) -Raw | ConvertFrom-Json
    $targetBuild = Get-Content -LiteralPath (
        Join-Path $targetRoot "BEKKI_BUILD.json"
    ) -Raw | ConvertFrom-Json
    if ($sourceBuild.build_id -ne $targetBuild.build_id) {
        throw (
            "Installed build metadata mismatch: " +
            $targetBuild.build_id + " != " + $sourceBuild.build_id
        )
    }
    $targetMain = Get-Content -LiteralPath (
        Join-Path $targetRoot "main.py"
    ) -Raw
    if ($targetMain.IndexOf(
        [string]$sourceBuild.build_id,
        [StringComparison]::Ordinal
    ) -lt 0) {
        throw "Installed main.py does not contain the package build ID."
    }

    $python = "python"
    $venvPython = Join-Path $targetRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $python = $venvPython
    }
    $compileFiles = @(
        "main.py", "magi.py", "melchior.py", "model_runtime.py",
        "tools.py", "vision.py", "worker.py", "casper\core.py",
        "casper\adapters.py", "casper\browser.py"
    ) | ForEach-Object { Join-Path $targetRoot $_ }
    & $python -m py_compile @compileFiles
    if ($LASTEXITCODE -ne 0) {
        throw "Python compile validation failed (exit code $LASTEXITCODE)."
    }
    if ($RunTests) {
        Push-Location $targetRoot
        try {
            & $python -m unittest discover -s tests -q
            if ($LASTEXITCODE -ne 0) {
                throw "Bekki unit tests failed (exit code $LASTEXITCODE)."
            }
        } finally {
            Pop-Location
        }
    }
} catch {
    Restore-StableRuntime
    throw (
        "Bekki Stable V1.3.9.5 installation failed and the previous runtime was " +
        "restored. Backup retained at: " + $backupRoot +
        [Environment]::NewLine + $_.Exception.Message
    )
}

Write-Host "Bekki Stable V1.3.9.5 installed successfully."
Write-Host "Target: $targetRoot"
Write-Host "Backup: $backupRoot"
Write-Host "Preserved: data, .env, .git, .venv, build, dist"
