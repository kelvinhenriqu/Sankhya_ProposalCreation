$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "Ambiente .venv não encontrado. Execute: uv sync --extra dev"
}

$converter = if ($env:PDF_CONVERTER) { $env:PDF_CONVERTER } else { "libreoffice" }
if ($converter -eq "word") {
    & $projectPython -c "import pythoncom, win32com.client"
    if ($LASTEXITCODE -ne 0) {
        throw "pywin32 não está disponível no .venv. Execute: uv sync --extra dev"
    }
}

Set-Location -LiteralPath $projectRoot
& $projectPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
