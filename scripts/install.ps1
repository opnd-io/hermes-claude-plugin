# hermes-bridge — Windows preflight + venv 캡처 (PowerShell). install.sh 와 기능 동등.
# SoT: docs/plan-2-plugin.md §2.3 + docs/plan-3-implementation.md (W2/W4/D1/C7/§14)
# 점검/안내 + venv 경로 기록만. 키 자동 기록 없음, curl|sh 없음.
$ErrorActionPreference = 'Stop'
$ApiBase = if ($env:HERMES_API_BASE) { $env:HERMES_API_BASE } else { 'http://127.0.0.1:8642' }
$Here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvOut = Join-Path $env:USERPROFILE '.hermes-bridge\env.cmd'
$Failed = 0
function Ok($m)   { Write-Host "  [ OK ] $m" }
function Warn($m) { Write-Host "  [WARN] $m" }
function Fail($m) { Write-Host "  [FAIL] $m"; $script:Failed = 1 }

Write-Host "== hermes-bridge preflight (Windows) =="

# 1) hermes CLI
Write-Host "[1/6] hermes CLI"
$HermesBin = (Get-Command hermes -ErrorAction SilentlyContinue).Source
if ($HermesBin) { Ok "hermes 발견: $HermesBin" } else { Fail "hermes CLI 없음 — Hermes Agent 먼저 설치" }

# 2) Hermes venv python 캡처 + mcp/httpx sanity (W4, D6=B)
Write-Host "[2/6] Hermes venv python"
$VenvPy = $null
if ($HermesBin) {
  $HbDir = Split-Path -Parent $HermesBin
  foreach ($c in @('python.exe','python3.exe')) {
    $cand = Join-Path $HbDir $c
    if (Test-Path $cand) { $VenvPy = $cand; break }
  }
}
if ($VenvPy) {
  & $VenvPy -c "import mcp, httpx" 2>$null
  if ($LASTEXITCODE -eq 0) {
    Ok "venv python: $VenvPy (mcp+httpx import OK)"
    New-Item -ItemType Directory -Force (Split-Path -Parent $EnvOut) | Out-Null
    # env.cmd — wrapper(bin/hermes-mcp-gateway.cmd)가 call 한다. 절대경로 (PATH 미상속 대비)
    @(
      "@echo off",
      "set `"HERMES_VENV_PY=$VenvPy`"",
      "set `"HERMES_BIN=$HermesBin`""
    ) | Set-Content -Path $EnvOut -Encoding OEM  # m11: 콘솔 codepage(cp949 등) — 한글 경로 보존
    Ok "경로 기록: $EnvOut"
  } else { Fail "venv python mcp/httpx import 실패 — Hermes 설치 확인 (FP8)" }
} else { Fail "venv python 미발견 (FP8)" }

# 3) API server 설정
Write-Host "[3/6] API server 설정"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:USERPROFILE '.hermes' }
$EnvFile = Join-Path $HermesHome '.env'
if ((Test-Path $EnvFile) -and (Select-String -Path $EnvFile -Pattern '^API_SERVER_ENABLED=true' -Quiet)) {
  Ok "API_SERVER_ENABLED=true ($EnvFile)"
} else {
  Fail "API server 미활성. $EnvFile 에 API_SERVER_ENABLED=true / HOST=127.0.0.1 / PORT=8642 / KEY=강한키 추가"
}

# 4) HERMES_API_KEY strong-key (§14, 값 비표시)
Write-Host "[4/6] HERMES_API_KEY (strong-key)"
$Key = $env:HERMES_API_KEY
if (-not $Key) { Fail "HERMES_API_KEY 미설정 — env로 주입(키 미기록)" }
elseif ($Key.Length -lt 32) { Fail "HERMES_API_KEY 너무 짧음 ($($Key.Length)자 < 32)" }
elseif ($Key -match '(?i)changeme|placeholder|your[-_]?key|x{16,}') { Fail "HERMES_API_KEY placeholder 로 보임" }
else { Ok "HERMES_API_KEY 설정됨 (≥32자, 비표시)" }

# 5) API server 연결 (키를 argv 노출 없이 — Invoke-WebRequest 헤더, C7)
Write-Host "[5/6] API server 연결 ($ApiBase/v1/models)"
if ($Key) {
  try {
    $resp = Invoke-WebRequest -Uri "$ApiBase/v1/models" -Headers @{ Authorization = "Bearer $Key" } -UseBasicParsing -TimeoutSec 10
    if ($resp.StatusCode -eq 200) { Ok "200 OK" } else { Fail "HTTP $($resp.StatusCode)" }
  } catch {
    $resp = $_.Exception.Response  # m13: null-guard (DNS/refused 시 null) + PS7/5.1 양쪽
    if ($null -ne $resp -and $resp.StatusCode.value__ -eq 401) { Fail "401 — 키 불일치" }
    elseif ($null -ne $resp) { Fail "HTTP $($resp.StatusCode.value__)" }
    else { Fail "연결 실패 — API server 미기동?" }
  }
} else { Write-Host "  [SKIP] 키 부재" }

# 6) gateway + 어댑터 무결성 (D1)
Write-Host "[6/6] gateway 상태 + 어댑터 무결성"
if ($HermesBin) {
  hermes gateway status *> $null
  if ($LASTEXITCODE -eq 0) { Ok "gateway 동작 중" } else { Warn "gateway 미가동 — cron 미발화 (§1.3, F2)" }
}
$SumFile = Join-Path $Here 'bin\hermes-mcp-gateway.sha256'
if (Test-Path $SumFile) {
  $mismatch = 0; $checked = 0
  foreach ($line in (Get-Content $SumFile)) {
    if ($line -notmatch '\S') { continue }
    # 포맷: "<hash> [*]<filename>" (sha256sum). 파일명에서 binary-mode '*' 제거.
    $parts = $line -split '\s+', 2
    if ($parts.Count -lt 2) { continue }
    $expected = $parts[0].ToLower()
    $fname = $parts[1].Trim().TrimStart('*')
    $fpath = Join-Path $Here ("bin\" + $fname)
    if (-not (Test-Path $fpath)) { $mismatch = 1; continue }
    $actual = (Get-FileHash $fpath -Algorithm SHA256).Hash.ToLower()
    $checked++
    if ($expected -ne $actual) { $mismatch = 1 }
  }
  if ($checked -gt 0 -and $mismatch -eq 0) { Ok "어댑터 체크섬 일치 ($checked 파일)" }
  else { Fail "체크섬 불일치/검증 실패 — 변조 의심 (D1/C9)" }
} else { Warn "체크섬 파일 부재 (개발 모드)" }

Write-Host "== 완료 (FAILED=$Failed) =="
exit $Failed
