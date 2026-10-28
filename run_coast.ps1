# 해안국 관리자 화면 띄우기 — .\run_coast.ps1 [-Port 8800] [-BindHost 127.0.0.1]
# 설정은 저장소 뿌리 .env.local(견본 .env.example). 종료는 Ctrl+C — 백그라운드에 아무것도 남지 않는다.
param(
    [int]$Port = 0,
    [string]$BindHost = "127.0.0.1",
    [switch]$Reload
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# .env.local → 비어 있는 환경변수만 채운다 (파이썬 coast/settings.py 와 같은 규칙)
$envFile = Join-Path $root ".env.local"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
        $l = $line.Trim()
        if ($l -eq "" -or $l.StartsWith("#") -or -not $l.Contains("=")) { continue }
        $k, $v = $l.Split("=", 2); $k = $k.Trim(); $v = $v.Trim().Trim('"').Trim("'")
        if ($k -ne "" -and -not (Test-Path "env:$k")) { Set-Item -Path "env:$k" -Value $v }
    }
}
if ($Port -eq 0) { $Port = if ($env:COAST_PORT) { [int]$env:COAST_PORT } else { 8800 } }

$py = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "venv 가 없습니다. 먼저:" -ForegroundColor Yellow
    Write-Host "  py -3.12 -m venv venv; .\venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}
$env:PYTHONIOENCODING = "utf-8"
Write-Host "해안국 관리자 화면  http://$BindHost`:$Port   (Ctrl+C 로 종료)" -ForegroundColor Cyan
$args_ = @("-m", "uvicorn", "coast.app:app", "--host", $BindHost, "--port", "$Port")
if ($Reload) { $args_ += "--reload" }
& $py @args_
