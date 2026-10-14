$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:MOVIEFLIX_MODE = 'local'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno virtual.' }
    & $pythonPath -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
}
& $pythonPath -m streamlit run app.py --server.address 127.0.0.1 --server.port 8510
