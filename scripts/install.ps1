[CmdletBinding()]
param(
    [string]$Version = $(if ($env:STACKMARSHAL_VERSION) { $env:STACKMARSHAL_VERSION } else { "latest" }),
    [switch]$Yes,
    [switch]$Force,
    [switch]$AllowDowngrade,
    [switch]$CliOnly,
    [switch]$SkillOnly,
    [switch]$NoPath,
    [string]$InstallRoot = $env:STACKMARSHAL_INSTALL_ROOT,
    [string]$CodexHome = $(if ($env:STACKMARSHAL_CODEX_HOME) { $env:STACKMARSHAL_CODEX_HOME } else { $env:CODEX_HOME }),
    [string]$RepositoryUrl = $(if ($env:STACKMARSHAL_REPOSITORY_URL) { $env:STACKMARSHAL_REPOSITORY_URL } else { "https://github.com/Soph1yzzz/stackmarshal.git" }),
    [string]$ReleaseBasePrefix = $(if ($env:STACKMARSHAL_RELEASE_BASE_PREFIX) { $env:STACKMARSHAL_RELEASE_BASE_PREFIX } else { "https://github.com/Soph1yzzz/stackmarshal/releases/download" })
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
if ($env:STACKMARSHAL_ASSUME_YES -eq "1") { $Yes = $true }
if ($env:STACKMARSHAL_NO_PATH -eq "1") { $NoPath = $true }

function Confirm-StackMarshalAction {
    param([Parameter(Mandatory = $true)][string]$Message)
    if ($Yes) { return $true }
    $answer = Read-Host "$Message [y/N]"
    return $answer -match '^(?i:y|yes)$'
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($machine, $user, $env:Path) | Where-Object { $_ }
    $env:Path = ($parts -join [IO.Path]::PathSeparator)
}

function Find-Git {
    $command = Get-Command git -ErrorAction SilentlyContinue | Where-Object { $_.CommandType -eq 'Application' } | Select-Object -First 1
    if ($command) { return $command.Source }
    $candidates = @(
        "$env:ProgramFiles\Git\cmd\git.exe",
        "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
    }
    return $null
}

function Ensure-Git {
    $git = Find-Git
    if ($git) { return $git }
    if (-not (Confirm-StackMarshalAction "Git was not found. Install Git for Windows with winget?")) {
        throw "Git is required. Install Git and rerun this command."
    }
    $winget = Get-Command winget -ErrorAction SilentlyContinue | Where-Object { $_.CommandType -eq 'Application' } | Select-Object -First 1
    if (-not $winget) {
        throw "winget is unavailable. Install Git from https://git-scm.com/download/win and rerun this command."
    }
    & $winget.Source install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget could not install Git." }
    Refresh-ProcessPath
    $git = Find-Git
    if (-not $git) { throw "Git was installed but is not visible yet. Open a new PowerShell window and rerun the installer." }
    return $git
}

function Test-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$Prefix = @()
    )
    try {
        # Avoid quoted Python literals: Windows PowerShell may strip nested quotes when
        # constructing a native command line.
        $code = 'import sys; print(sys.executable); print(sys.version_info[0],sys.version_info[1],sys.version_info[2],sep=chr(46))'
        $raw = @(& $Command @Prefix -I -c $code 2>$null)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -lt 2) { return $null }
        $detectedVersion = [version]$raw[-1]
        if (($detectedVersion.Major -gt 3) -or (($detectedVersion.Major -eq 3) -and ($detectedVersion.Minor -ge 11))) {
            return [pscustomobject]@{ Executable = [string]$raw[0]; Version = $detectedVersion.ToString() }
        }
    } catch {
        return $null
    }
    return $null
}

function Find-Python {
    $found = @()
    $seen = @{}
    $launcher = Get-Command py -ErrorAction SilentlyContinue | Where-Object { $_.CommandType -eq 'Application' } | Select-Object -First 1
    if ($launcher) {
        try {
            $installed = & $launcher.Source -0p 2>$null
            foreach ($line in $installed) {
                if ($line -match '([A-Za-z]:\\.*python(?:w)?\.exe)\s*$') {
                    $candidate = $Matches[1]
                    $key = $candidate.ToLowerInvariant()
                    if (-not $seen.ContainsKey($key)) {
                        $seen[$key] = $true
                        $result = Test-PythonCandidate -Command $candidate
                        if ($result) { $found += $result }
                    }
                }
            }
        } catch { }
    }
    foreach ($command in @("python", "python3")) {
        $resolved = Get-Command $command -ErrorAction SilentlyContinue | Where-Object { $_.CommandType -eq 'Application' } | Select-Object -First 1
        if (-not $resolved) { continue }
        $key = $resolved.Source.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $result = Test-PythonCandidate -Command $resolved.Source
        if ($result) { $found += $result }
    }
    $supported = @($found | Where-Object { ([version]$_.Version) -lt [version]'3.14' } | Sort-Object { [version]$_.Version } -Descending)
    if ($supported.Count -gt 0) { return $supported[0] }
    $newer = @($found | Sort-Object { [version]$_.Version } -Descending)
    if ($newer.Count -gt 0) { return $newer[0] }
    return $null
}

function Ensure-Python {
    $python = Find-Python
    if ($python) { return $python }
    if (-not (Confirm-StackMarshalAction "Python 3.11 or newer was not found. Install Python 3.13 with winget?")) {
        throw "Python 3.11 or newer is required. Install it and rerun this command."
    }
    $winget = Get-Command winget -ErrorAction SilentlyContinue | Where-Object { $_.CommandType -eq 'Application' } | Select-Object -First 1
    if (-not $winget) {
        throw "winget is unavailable. Install Python 3.11+ from https://www.python.org/downloads/ and rerun this command."
    }
    & $winget.Source install --id Python.Python.3.13 -e --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget could not install Python 3.13." }
    Refresh-ProcessPath
    $python = Find-Python
    if (-not $python) { throw "Python was installed but is not visible yet. Open a new PowerShell window and rerun the installer." }
    return $python
}

function Test-VenvSupport {
    param([Parameter(Mandatory = $true)][string]$Python)
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ("stackmarshal-venv-check-" + [guid]::NewGuid().ToString("N"))
    try {
        & $Python -I -m venv (Join-Path $temporary "venv") *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Ensure-VenvSupport {
    param([Parameter(Mandatory = $true)][pscustomobject]$Python)
    if (-not (Test-VenvSupport -Python $Python.Executable)) {
        throw "Python $($Python.Version) cannot create virtual environments. Repair or reinstall Python with the venv/ensurepip component, then rerun the installer."
    }
}

function Resolve-Version {
    param(
        [Parameter(Mandatory = $true)][string]$Requested,
        [Parameter(Mandatory = $true)][string]$Git
    )
    if ($Requested -ne "latest") {
        if ($Requested -notmatch '^v?\d+\.\d+\.\d+$') { throw "Invalid version: $Requested" }
        return "v$($Requested.TrimStart('v'))"
    }
    $lines = & $Git ls-remote --tags --refs $RepositoryUrl "refs/tags/v*"
    if ($LASTEXITCODE -ne 0) { throw "Could not query StackMarshal release tags." }
    $versions = foreach ($line in $lines) {
        if ($line -match 'refs/tags/(v\d+\.\d+\.\d+)$') {
            $tag = $Matches[1]
            try { [pscustomobject]@{ Tag = $tag; Value = [version]$tag.Substring(1) } } catch { }
        }
    }
    $latest = $versions | Sort-Object Value -Descending | Select-Object -First 1
    if (-not $latest) { throw "No stable StackMarshal release tag was found." }
    return $latest.Tag
}

function Assert-SafeDownloadUrl {
    param([Parameter(Mandatory = $true)][string]$Url)
    try { $uri = [Uri]$Url } catch { throw "Invalid download URL: $Url" }
    if (-not $uri.IsAbsoluteUri -or $uri.UserInfo) { throw "Unsafe download URL: $Url" }
    if ($uri.Scheme -eq 'https') { return }
    if ($uri.Scheme -eq 'http' -and $uri.IsLoopback) { return }
    throw "Unsafe download URL: $Url"
}

function Invoke-Download {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    Assert-SafeDownloadUrl -Url $Url
    Add-Type -AssemblyName System.Net.Http
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $true
    $client = [System.Net.Http.HttpClient]::new($handler)
    $response = $null
    $source = $null
    $output = $null
    try {
        $response = $client.GetAsync(
            $Url,
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "Download failed with HTTP $([int]$response.StatusCode): $Url"
        }
        Assert-SafeDownloadUrl -Url ([string]$response.RequestMessage.RequestUri)
        if ($response.Content.Headers.ContentLength -and $response.Content.Headers.ContentLength -gt 4MB) {
            throw "Bootstrap download is too large: $Url"
        }
        $source = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $output = [IO.File]::Open(
            $Destination,
            [IO.FileMode]::Create,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )
        $buffer = New-Object byte[] 65536
        [long]$total = 0
        while (($read = $source.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $total += $read
            if ($total -gt 4MB) { throw "Bootstrap download is too large: $Url" }
            $output.Write($buffer, 0, $read)
        }
    } finally {
        if ($output) { $output.Dispose() }
        if ($source) { $source.Dispose() }
        if ($response) { $response.Dispose() }
        $client.Dispose()
        $handler.Dispose()
    }
    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) {
        throw "Download did not create a regular file: $Url"
    }
    if ((Get-Item -LiteralPath $Destination).Length -eq 0) {
        throw "Downloaded file is empty: $Url"
    }
}

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        $stream = [IO.File]::OpenRead($Path)
        $hash = $algorithm.ComputeHash($stream)
        return ([BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant()
    } finally {
        if ($stream) { $stream.Dispose() }
        $algorithm.Dispose()
    }
}

function Get-ExpectedHash {
    param(
        [Parameter(Mandatory = $true)][string]$ChecksumFile,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $entries = [System.Collections.Generic.Dictionary[string,string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $lineNumber = 0
    foreach ($line in Get-Content -LiteralPath $ChecksumFile) {
        $lineNumber += 1
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -notmatch '^([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+-]*)$') {
            throw "Malformed SHA256SUMS line $lineNumber"
        }
        $digest = $Matches[1]
        $entryName = $Matches[2]
        if ($entries.ContainsKey($entryName)) { throw "Duplicate checksum entry: $entryName" }
        $entries.Add($entryName, $digest)
    }
    if (-not $entries.ContainsKey($Name)) { throw "SHA256SUMS does not contain $Name" }
    return $entries[$Name]
}

$temporary = $null
try {
    if ($CliOnly -and $SkillOnly) { throw "-CliOnly and -SkillOnly cannot be combined." }
    $git = Ensure-Git
    $python = Ensure-Python
    Ensure-VenvSupport -Python $python
    $tag = Resolve-Version -Requested $Version -Git $git
    $normalized = $tag.Substring(1)
    $releaseBase = "$($ReleaseBasePrefix.TrimEnd('/'))/$tag"

    $temporary = Join-Path ([IO.Path]::GetTempPath()) ("stackmarshal-bootstrap-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $temporary | Out-Null
    $checksums = Join-Path $temporary "SHA256SUMS"
    $installer = Join-Path $temporary "installer.py"
    Invoke-Download -Url "$releaseBase/SHA256SUMS" -Destination $checksums
    Invoke-Download -Url "$releaseBase/installer.py" -Destination $installer
    $expected = Get-ExpectedHash -ChecksumFile $checksums -Name "installer.py"
    $actual = Get-Sha256Hex -Path $installer
    if ($actual -ne $expected) { throw "Checksum mismatch for installer.py" }

    $arguments = @(
        $installer,
        "--version", $normalized,
        "--release-base-url", $releaseBase,
        "--repository-url", $RepositoryUrl
    )
    if ($Yes) { $arguments += "--yes" }
    if ($Force) { $arguments += "--force" }
    if ($AllowDowngrade) { $arguments += "--allow-downgrade" }
    if ($CliOnly) { $arguments += "--cli-only" }
    if ($SkillOnly) { $arguments += "--skill-only" }
    if ($NoPath) { $arguments += "--no-path" }
    if ($InstallRoot) { $arguments += @("--install-root", $InstallRoot) }
    if ($CodexHome) { $arguments += @("--codex-home", $CodexHome) }

    & $python.Executable -I @arguments
    if ($LASTEXITCODE -ne 0) { throw "StackMarshal installation failed." }
} finally {
    if ($temporary -and (Test-Path -LiteralPath $temporary)) {
        Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
    }
}
