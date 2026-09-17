$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repository = "tsuru-kiri/msr-dl"
$LatestReleaseApi = "https://api.github.com/repos/$Repository/releases/latest"
$UvInstallerUrl = "https://astral.sh/uv/install.ps1"
$FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
$Step = 0
$StepCount = 5
$TempDirectory = $null
$FfmpegStagingRoot = $null

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)

    $script:Step++
    Write-Host "[$script:Step/$script:StepCount] $Message"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter()][string[]]$ArgumentList = @()
    )

    $output = & $FilePath @ArgumentList 2>&1
    if ($LASTEXITCODE -ne 0) {
        $detail = ($output | Out-String).Trim()
        throw "Command failed: $FilePath $($ArgumentList -join ' ')`n$detail"
    }
    return $output
}

function Add-PathEntry {
    param([Parameter(Mandatory = $true)][string]$Directory)

    $fullPath = [System.IO.Path]::GetFullPath($Directory).TrimEnd('\', '/')
    $processEntries = @($env:Path -split ';' | Where-Object { $_ })
    if (-not ($processEntries | Where-Object {
        $_.TrimEnd('\', '/') -ieq $fullPath
    })) {
        $env:Path = "$fullPath;$env:Path"
    }

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $userEntries = @($userPath -split ';' | Where-Object { $_ })
    if (-not ($userEntries | Where-Object {
        $_.TrimEnd('\', '/') -ieq $fullPath
    })) {
        [Environment]::SetEnvironmentVariable(
            "Path",
            (@($fullPath) + $userEntries) -join ';',
            "User"
        )
    }
}

function Find-UvExecutable {
    $command = Get-Command "uv.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    $candidates = @()
    if ($env:UV_INSTALL_DIR) {
        $candidates += Join-Path $env:UV_INSTALL_DIR "uv.exe"
    }
    if ($env:XDG_BIN_HOME) {
        $candidates += Join-Path $env:XDG_BIN_HOME "uv.exe"
    }
    if ($env:XDG_DATA_HOME) {
        $candidates += Join-Path (Join-Path $env:XDG_DATA_HOME "..\bin") "uv.exe"
    }
    $candidates += Join-Path $HOME ".local\bin\uv.exe"

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    return $null
}

function ConvertTo-StableVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
        throw "Invalid $Label version: $Value"
    }
    return [Version]::new(
        [int]$Matches[1],
        [int]$Matches[2],
        [int]$Matches[3]
    )
}

try {
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        throw "PowerShell 5.1 or newer is required."
    }
    if ($env:OS -ne "Windows_NT") {
        throw "This installer only supports Windows."
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "A 64-bit version of Windows is required."
    }
    if (-not $env:LOCALAPPDATA) {
        throw "LOCALAPPDATA is not available."
    }

    $TempDirectory = Join-Path ([System.IO.Path]::GetTempPath()) (
        "msr-dl-install-" + [Guid]::NewGuid().ToString("N")
    )
    New-Item -ItemType Directory -Path $TempDirectory | Out-Null

    Write-Step "Checking uv"
    $uv = Find-UvExecutable
    if ($null -eq $uv) {
        Write-Host "  Installing uv..."
        $installer = Invoke-RestMethod -UseBasicParsing -Uri $UvInstallerUrl
        Invoke-Expression $installer
        $uv = Find-UvExecutable
        if ($null -eq $uv) {
            throw "uv was installed but uv.exe could not be found."
        }
    }
    $uvVersion = (Invoke-Checked $uv @("--version") | Select-Object -First 1)
    Write-Host "  $uvVersion"

    $toolBin = (Invoke-Checked $uv @("tool", "dir", "--bin") | Select-Object -First 1).Trim()
    if (-not $toolBin) {
        throw "uv did not report its tool executable directory."
    }
    Add-PathEntry $toolBin

    Write-Step "Checking FFmpeg"
    $ffmpegCommand = Get-Command "ffmpeg.exe" -ErrorAction SilentlyContinue
    $managedFfmpegRoot = Join-Path $env:LOCALAPPDATA "msr-dl\ffmpeg"
    $managedFfmpeg = Join-Path $managedFfmpegRoot "bin\ffmpeg.exe"
    if ($null -ne $ffmpegCommand) {
        $ffmpeg = $ffmpegCommand.Source
        Write-Host "  Using FFmpeg from PATH."
    } elseif (Test-Path -LiteralPath $managedFfmpeg -PathType Leaf) {
        $ffmpeg = $managedFfmpeg
        Write-Host "  Using the existing msr-dl FFmpeg installation."
    } else {
        Write-Host "  Installing FFmpeg for msr-dl..."
        $ffmpegArchive = Join-Path $TempDirectory "ffmpeg.zip"
        $ffmpegExtract = Join-Path $TempDirectory "ffmpeg-extracted"
        Invoke-WebRequest -UseBasicParsing -Uri $FfmpegUrl -OutFile $ffmpegArchive
        Expand-Archive -LiteralPath $ffmpegArchive -DestinationPath $ffmpegExtract

        $ffmpegFiles = @(Get-ChildItem -LiteralPath $ffmpegExtract -Recurse -File |
            Where-Object { $_.Name -ieq "ffmpeg.exe" -and $_.Directory.Name -ieq "bin" })
        if ($ffmpegFiles.Count -ne 1) {
            throw "The FFmpeg archive did not contain exactly one bin\ffmpeg.exe."
        }

        $sourceRoot = $ffmpegFiles[0].Directory.Parent.FullName
        $managedParent = Split-Path -Parent $managedFfmpegRoot
        New-Item -ItemType Directory -Force -Path $managedParent | Out-Null
        $FfmpegStagingRoot = Join-Path $managedParent (
            ".ffmpeg-" + [Guid]::NewGuid().ToString("N")
        )
        Copy-Item -LiteralPath $sourceRoot -Destination $FfmpegStagingRoot -Recurse
        if (-not (Test-Path -LiteralPath (Join-Path $FfmpegStagingRoot "bin\ffmpeg.exe") -PathType Leaf)) {
            throw "The staged FFmpeg installation is incomplete."
        }
        if (Test-Path -LiteralPath $managedFfmpegRoot) {
            Remove-Item -LiteralPath $managedFfmpegRoot -Recurse -Force
        }
        Move-Item -LiteralPath $FfmpegStagingRoot -Destination $managedFfmpegRoot
        $FfmpegStagingRoot = $null
        $ffmpeg = $managedFfmpeg
    }

    Write-Step "Checking the latest msr-dl release"
    $headers = @{ Accept = "application/vnd.github+json"; "User-Agent" = "msr-dl-installer" }
    $release = Invoke-RestMethod -UseBasicParsing -Headers $headers -Uri $LatestReleaseApi
    if ($release.draft -or $release.prerelease) {
        throw "GitHub returned a draft or prerelease as the latest release."
    }
    if ($release.tag_name -notmatch '^v(.+)$') {
        throw "Invalid release tag: $($release.tag_name)"
    }
    $latestText = $Matches[1]
    $latestVersion = ConvertTo-StableVersion $latestText "release"
    $wheelName = "msr_dl-$latestText-py3-none-any.whl"
    $wheelAssets = @($release.assets | Where-Object { $_.name -ceq $wheelName })
    if ($wheelAssets.Count -ne 1) {
        throw "Release $($release.tag_name) must contain exactly one $wheelName asset."
    }
    $wheelAsset = $wheelAssets[0]
    if ($wheelAsset.digest -notmatch '^sha256:([0-9a-fA-F]{64})$') {
        throw "The release wheel does not have a valid SHA-256 digest."
    }
    $expectedWheelHash = $Matches[1]
    Write-Host "  Latest version: $latestText"

    Write-Step "Installing or updating msr-dl"
    $msrDl = Join-Path $toolBin "msr-dl.exe"
    $installedText = $null
    $installedVersion = $null
    if (Test-Path -LiteralPath $msrDl -PathType Leaf) {
        $installedOutput = (Invoke-Checked $msrDl @("--version") | Select-Object -First 1).Trim()
        if ($installedOutput -notmatch '^msr-dl (.+)$') {
            throw "Could not read the installed msr-dl version: $installedOutput"
        }
        $installedText = $Matches[1]
        $installedVersion = ConvertTo-StableVersion $installedText "installed"
    }

    if ($null -eq $installedVersion -or $installedVersion -lt $latestVersion) {
        $wheelPath = Join-Path $TempDirectory $wheelName
        Invoke-WebRequest -UseBasicParsing -Uri $wheelAsset.browser_download_url -OutFile $wheelPath
        $actualWheelHash = (Get-FileHash -LiteralPath $wheelPath -Algorithm SHA256).Hash
        if ($actualWheelHash -ine $expectedWheelHash) {
            throw "The downloaded wheel failed SHA-256 verification."
        }
        Invoke-Checked $uv @("tool", "install", "--quiet", "--force", $wheelPath) | Out-Null
        Write-Host "  Installed msr-dl $latestText."
    } elseif ($installedVersion -eq $latestVersion) {
        Write-Host "  msr-dl $installedText is already up to date."
    } else {
        Write-Host "  Keeping newer installed version $installedText."
    }

    Write-Step "Verifying the installation"
    $finalUv = (Invoke-Checked $uv @("--version") | Select-Object -First 1).Trim()
    $finalFfmpeg = (Invoke-Checked $ffmpeg @("-version") | Select-Object -First 1).Trim()
    $finalMsrDl = (Invoke-Checked $msrDl @("--version") | Select-Object -First 1).Trim()
    Write-Host "  $finalUv"
    Write-Host "  $finalFfmpeg"
    Write-Host "  $finalMsrDl"
    Write-Host ""
    Write-Host "Installation complete. Open a new terminal and run: msr-dl --help"
} catch {
    Write-Host ""
    [Console]::Error.WriteLine("Installation failed: $($_.Exception.Message)")
    exit 1
} finally {
    if ($null -ne $FfmpegStagingRoot -and (Test-Path -LiteralPath $FfmpegStagingRoot)) {
        Remove-Item -LiteralPath $FfmpegStagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $TempDirectory -and (Test-Path -LiteralPath $TempDirectory)) {
        Remove-Item -LiteralPath $TempDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
}
