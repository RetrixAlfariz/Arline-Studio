[CmdletBinding()]
param(
    [switch]$Headless,
    [switch]$SkipBuild,
    [switch]$DebugBuild,
    [switch]$BuildOnly,
    [string]$DataDirectory = (Join-Path $env:LOCALAPPDATA 'Arline Studio'),
    [ValidateRange(0,65535)][int]$Port = 7861
)
$ErrorActionPreference = 'Stop'
$manifest = Join-Path $PSScriptRoot 'crates/arline-runtime/Cargo.toml'
$profile = if ($DebugBuild) { 'debug' } else { 'release' }
if (-not $SkipBuild) {
    # Configure this process only. Some Windows shells omit the SDK linker paths.
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (Test-Path -LiteralPath $vswhere) {
        $vsPath = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        $toolchain = Get-ChildItem (Join-Path $vsPath 'VC/Tools/MSVC') -Directory | Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
        $sdkRoot = (Get-ItemProperty 'HKLM:/SOFTWARE/Microsoft/Windows Kits/Installed Roots' -Name KitsRoot10).KitsRoot10
        $sdk = Get-ChildItem (Join-Path $sdkRoot 'Lib') -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'um/x64/kernel32.lib') } | Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
        if ($toolchain -and $sdk) {
            $env:LIB = @((Join-Path $toolchain.FullName 'lib/x64'),(Join-Path $sdk.FullName 'um/x64'),(Join-Path $sdk.FullName 'ucrt/x64'),$env:LIB) -join ';'
        }
    }
    Push-Location (Join-Path $PSScriptRoot 'frontend')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    $buildArguments = @('build','--locked','--manifest-path',$manifest,'--features','desktop')
    if (-not $DebugBuild) { $buildArguments += '--release' }
    & cargo @buildArguments
    if ($LASTEXITCODE -ne 0) { throw 'Rust desktop build failed.' }
}
$executable = Join-Path $PSScriptRoot "crates/arline-runtime/target/$profile/arline.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Native executable is missing: $executable. Run without -SkipBuild."
}
if ($BuildOnly) { Write-Output $executable; return }
# Rust copies configuration, SQLite (including WAL), and managed media only on first
# launch. All ongoing writes go to DataDirectory; the original project stays intact.
$launchArguments = @('--bootstrap-from',$PSScriptRoot,'--data-dir',$DataDirectory,'--port',"$Port")
if ($Headless) { $launchArguments += '--headless' }
$startInfo = [Diagnostics.ProcessStartInfo]::new($executable)
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
foreach ($argument in $launchArguments) { $startInfo.ArgumentList.Add($argument) }
$nativeProcess = [Diagnostics.Process]::Start($startInfo)
$nativeProcess.WaitForExit()
if ($nativeProcess.ExitCode -ne 0) { throw "Arline exited with code $($nativeProcess.ExitCode)." }
