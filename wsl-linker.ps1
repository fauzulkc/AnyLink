# PowerShell Wrapper for wsl-linker
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$cliScript = Join-Path $scriptDir "wsl_linker.py"

if (-not (Test-Path $cliScript)) {
    Write-Error "wsl_linker.py not found in script directory: $scriptDir"
}

# Run the python script forwarding all arguments
python $cliScript @args
