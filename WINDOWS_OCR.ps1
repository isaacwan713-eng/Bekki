[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath,
    [string]$PreferredLanguageTag = "zh-CN"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Write-OcrResult([hashtable]$Value) {
    $Value | ConvertTo-Json -Compress -Depth 6
}

try {
    $stage = "load_winrt"
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Foundation.IAsyncOperation`1, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Storage.Streams.RandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
    $null = [WindowsRuntimeSystemExtensions]

    $script:AwaiterMethod = (
        [WindowsRuntimeSystemExtensions].GetMember(
            "GetAwaiter",
            "Method",
            "Public,Static"
        ) |
        Where-Object {
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        } |
        Select-Object -First 1
    )
    if ($null -eq $script:AwaiterMethod) {
        throw "WinRT awaiter adapter is unavailable."
    }

    function Wait-WinRtOperation(
        [Parameter(Mandatory = $true)]
        [object]$Operation,
        [Parameter(Mandatory = $true)]
        [Type]$ResultType
    ) {
        $closedMethod = $script:AwaiterMethod.MakeGenericMethod($ResultType)
        $awaiter = $closedMethod.Invoke($null, @($Operation))
        return $awaiter.GetResult()
    }

    $stage = "select_language"
    $availableLanguages = @(
        [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages
    )
    $availableTags = @(
        $availableLanguages | ForEach-Object { [string]$_.LanguageTag }
    )

    $language = $availableLanguages |
        Where-Object {
            $_.LanguageTag -eq $PreferredLanguageTag
        } |
        Select-Object -First 1
    $languageMatch = "PREFERRED"
    $preferredAvailable = $null -ne $language

    if ($null -eq $language) {
        $language = $availableLanguages |
            Where-Object {
                $_.LanguageTag -like "zh-CN*" -or
                $_.LanguageTag -like "zh-Hans*" -or
                $_.LanguageTag -like "zh-SG*"
            } |
            Select-Object -First 1
        $languageMatch = "CHINESE_FALLBACK"
    }

    $engine = $null
    if ($null -ne $language) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    }
    if ($null -eq $engine) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
        $languageMatch = "PROFILE_FALLBACK"
    }
    if ($null -eq $engine) {
        Write-OcrResult @{
            status = "UNAVAILABLE"
            reason = "no_ocr_recognizer"
            language_tag = ""
            language_match = "NONE"
            preferred_language_available = $preferredAvailable
            available_languages = $availableTags
            text = ""
            lines = @()
        }
        exit 0
    }

    $stage = "open_image"
    $storageFile = Wait-WinRtOperation (
        [Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)
    ) ([Windows.Storage.StorageFile])
    $stream = Wait-WinRtOperation (
        $storageFile.OpenAsync([Windows.Storage.FileAccessMode]::Read)
    ) ([Windows.Storage.Streams.IRandomAccessStream])

    $stage = "decode_image"
    $decoder = Wait-WinRtOperation (
        [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
    ) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Wait-WinRtOperation (
        $decoder.GetSoftwareBitmapAsync()
    ) ([Windows.Graphics.Imaging.SoftwareBitmap])

    $stage = "recognize_text"
    $ocrResult = Wait-WinRtOperation (
        $engine.RecognizeAsync($bitmap)
    ) ([Windows.Media.Ocr.OcrResult])

    $lineRows = @(
        $ocrResult.Lines | ForEach-Object {
            @{
                text = [string]$_.Text
            }
        }
    )

    Write-OcrResult @{
        status = "COMPLETED"
        reason = ""
        language_tag = [string]$engine.RecognizerLanguage.LanguageTag
        language_match = $languageMatch
        preferred_language_available = $preferredAvailable
        available_languages = $availableTags
        text = [string]$ocrResult.Text
        lines = $lineRows
    }

    if ($null -ne $bitmap) {
        $bitmap.Dispose()
    }
    if ($null -ne $stream) {
        $stream.Dispose()
    }
} catch {
    Write-OcrResult @{
        status = "FAILED"
        reason = "winrt_ocr_failed"
        error_stage = [string]$stage
        error_type = $_.Exception.GetType().Name
        error_hresult = [string]$_.Exception.HResult
        language_tag = ""
        language_match = "NONE"
        preferred_language_available = $false
        available_languages = @()
        text = ""
        lines = @()
    }
}
