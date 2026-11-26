# proveflow installer (Windows PowerShell 5.1+). Phase 9; docs/INSTALL.md cites every fact used.
#
#   powershell -ExecutionPolicy ByPass -File install.ps1
#       install proveflow v$ProveflowVersion from its git tag, dependencies from PyPI
#   powershell -ExecutionPolicy ByPass -File install.ps1 -Wheelhouse DIR
#       install ONLY from DIR (proveflow's wheel AND every dependency wheel):
#       --find-links DIR --no-index, no package index at all (the CI evidence)
#
# If uv is not on PATH, it is installed first with uv's official installer at a PINNED version,
# into %USERPROFILE%\.local\bin (UV_INSTALL_DIR), without editing PATH (UV_NO_MODIFY_PATH=1).
# Afterwards the script checks that `proveflow` is on PATH and prints its version; any failure
# exits non-zero with a readable message.
param([string]$Wheelhouse = "")

$ErrorActionPreference = "Stop"
$ProveflowVersion = "0.1.0a1"     # == [project].version (CI checks the tag matches)
$UvVersion = "0.13.10"            # pinned uv installer version
$RepoUrl = "https://github.com/M-Haris346/proveflow"

function Fail([string]$Message) {
    [Console]::Error.WriteLine("proveflow installer: ERROR: $Message")
    exit 1
}
function Say([string]$Message) { Write-Output "proveflow installer: $Message" }

if ($Wheelhouse -ne "" -and -not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) {
    Fail "-Wheelhouse $Wheelhouse is not a directory"
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    Say "uv found: $($uv.Source)"
} else {
    $bin = Join-Path $env:USERPROFILE ".local\bin"
    Say "uv not found: installing uv $UvVersion (official installer, pinned) into $bin"
    $env:UV_INSTALL_DIR = $bin
    $env:UV_NO_MODIFY_PATH = "1"
    try {
        Invoke-Expression (Invoke-RestMethod "https://astral.sh/uv/$UvVersion/install.ps1")
    } catch {
        Fail "the uv installer failed: $($_.Exception.Message)"
    }
    $env:PATH = "$bin;$env:PATH"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Fail "uv was installed but is not on PATH" }
}

if ($Wheelhouse -ne "") {
    Say "installing proveflow==$ProveflowVersion from $Wheelhouse ONLY (--no-index)"
    & uv tool install "proveflow==$ProveflowVersion" --find-links $Wheelhouse --no-index
    if ($LASTEXITCODE -ne 0) { Fail "uv tool install from the wheelhouse failed" }
} else {
    Say "installing proveflow from git tag v$ProveflowVersion (dependencies from PyPI)"
    & uv tool install "git+$RepoUrl@v$ProveflowVersion"
    if ($LASTEXITCODE -ne 0) { Fail "uv tool install from the git tag failed" }
}

$pf = Get-Command proveflow -ErrorAction SilentlyContinue
if (-not $pf) {
    Fail "proveflow was installed but is not on PATH: add the directory printed by ``uv tool dir --bin`` to PATH (or run ``uv tool update-shell``), then open a new shell"
}
$got = (& proveflow --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { Fail "``proveflow --version`` failed" }
if ($got -ne "proveflow $ProveflowVersion") {
    Fail "installed version is '$got', expected 'proveflow $ProveflowVersion'"
}
Say "installed: $got ($($pf.Source))"
exit 0
