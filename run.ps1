# Run from any PowerShell folder:
# powershell -ExecutionPolicy Bypass -File .\run.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $found = $false
        foreach ($version in @('3.12', '3.11')) {
            & py "-$version" -c 'import sys; print(sys.version)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                & py "-$version" -m venv '.venv'
                $found = $true
                break
            }
        }
        if (-not $found) {
            throw 'Install Python 3.12 or 3.11, then run this script again.'
        }
    } else {
        throw 'Python launcher (py) not found. Install Python 3.12 or 3.11.'
    }
}
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $venvPython -m streamlit run app.py
