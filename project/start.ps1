param(
    [switch]$Mock,
    [switch]$Real
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "找不到 python，请先安装 Python 3.10+ 并加入 PATH。"
    }
    python -m venv .venv
}

Write-Host "安装依赖……"
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r requirements.txt

if ($Real -and -not (Test-Path (Join-Path $PSScriptRoot ".env"))) {
    throw "指定了 -Real，但 project/.env 不存在。请先 cp .env.example .env 并填写 MAAS_*。"
}

$useMock = $Mock -or ((-not $Real) -and -not (Test-Path (Join-Path $PSScriptRoot ".env")))
if ($useMock) {
    $env:MOCK_LLM = "1"
    Write-Host "模式：Mock（不请求真实模型）"
} else {
    Remove-Item Env:MOCK_LLM -ErrorAction SilentlyContinue
    Write-Host "模式：真实模型（读取 project/.env）"
}

Write-Host "打开：http://127.0.0.1:8000/blood"
Write-Host "按 Ctrl+C 停止。"
& $venvPython -m app.main