<#
  impulse-guard 한 번에 켜기 (7 마무리)

  웹 서버(php -S localhost:8001), 예측 서버(127.0.0.1:8002), 데스크톱 감지 프로그램을 각각 새 창으로 켜고,
  켠 프로세스 번호를 data\ipp_pids.json(Git 제외)에 적는다. 끄기는 scripts\stop.ps1

  사용 (저장소 루트에서):
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1                 평소 (위험도는 PHP 계산, AI 요약 꺼짐)
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Demo           시연 모드: 위험도를 예측 서버로 계산(IPP_RISK_SERVER=on),
                                                                              데스크톱은 데모 회원 설정(desktop\local_config.demo.json)
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Demo -Llm      + 통계 화면 AI 요약 버튼(IPP_USE_LLM=1)
    옵션: -NoAi(예측 서버 안 켬), -NoDesktop(데스크톱 안 켬), -DryRun(실행할 명령만 보여 줌)

  - 시연 모드 값은 이 스크립트가 켠 웹 서버에만 환경변수로 넘긴다. extend\ipp.extend.php는 바꾸지 않는다
  - API 키는 스크립트에 적지 않는다. 지금 터미널에 $env:ANTHROPIC_API_KEY가 있으면 예측 서버가 이어받는다
  - 이미 켜져 있는 서버(포트 사용 중)는 다시 켜지 않는다
#>
param(
    [switch]$Demo,
    [switch]$Llm,
    [switch]$NoAi,
    [switch]$NoDesktop,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root 'data\ipp_pids.json'
$aiPy    = Join-Path $root 'ai\.venv\Scripts\python.exe'
$dtPy    = Join-Path $root 'desktop\.venv\Scripts\python.exe'
$demoCfg = Join-Path $root 'desktop\local_config.demo.json'

function Test-Port([int]$port) {
    try { return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop) } catch { return $false }
}

function Get-Url([string]$url) {
    try { return Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 } catch { return $null }
}

if ($Llm -and -not $Demo) { Write-Host '-Llm은 -Demo와 함께 씁니다.'; exit 1 }
if ($Demo -and -not $NoDesktop -and -not (Test-Path $demoCfg)) {
    Write-Host '데모 회원 설정 파일이 없습니다. 먼저 php scripts\demo_seed.php add 를 실행하세요.'
    exit 1
}
if ($Llm -and -not $env:ANTHROPIC_API_KEY -and $env:IPP_AI_LLM_PROFILE -ne '1') {
    Write-Host '참고: ANTHROPIC_API_KEY가 없어 AI 요약 버튼을 누르면 "지금은 요약을 만들 수 없어요."가 나옵니다.'
}

$started = @{}
if (Test-Path $pidFile) {
    try { (Get-Content $pidFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $started[$_.Name] = $_.Value } } catch {}
}

function Start-Part([string]$name, [string]$exe, [string[]]$argList, [string]$dir, [hashtable]$envVars) {
    if ($DryRun) {
        $envText = ($envVars.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ' '
        Write-Host ("[DryRun] {0}: {1} {2}  (폴더 {3}) {4}" -f $name, $exe, ($argList -join ' '), $dir, $envText)
        return
    }
    if (-not (Test-Path $exe) -and $exe -notmatch '^php') { Write-Host "$name 실행 파일이 없습니다: $exe"; return }
    $saved = @{}
    foreach ($k in $envVars.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k, 'Process'); [Environment]::SetEnvironmentVariable($k, $envVars[$k], 'Process') }
    try {
        $p = Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $dir -PassThru
        $script:started[$name] = $p.Id
        Write-Host "$name 켬 (프로세스 $($p.Id))"
    } finally {
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], 'Process') }
    }
}

# 1. 웹 서버 (시연 모드 값은 환경변수로만)
$webEnv = @{}
if ($Demo) { $webEnv['IPP_RISK_SERVER'] = 'on' }
if ($Llm)  { $webEnv['IPP_USE_LLM'] = '1' }
if (Test-Port 8001) {
    Write-Host '웹 서버: 8001 포트가 이미 사용 중이라 새로 켜지 않습니다.'
    if ($Demo) { Write-Host '  주의: 시연 모드 값은 이 스크립트가 켠 웹 서버에만 적용됩니다. 지금 서버를 끄고 다시 실행하세요.' }
} else {
    Start-Part 'web' 'php' @('-S', 'localhost:8001') $root $webEnv
}

# 2. 예측 서버
if (-not $NoAi) {
    if (Test-Port 8002) { Write-Host '예측 서버: 8002 포트가 이미 사용 중이라 새로 켜지 않습니다.' }
    else { Start-Part 'ai' $aiPy @('-m', 'serve') (Join-Path $root 'ai') @{} }
}

# 3. 데스크톱 (시연 모드면 데모 회원 설정)
if (-not $NoDesktop) {
    $dtEnv = @{}
    if ($Demo) { $dtEnv['IPP_DESKTOP_CONFIG'] = $demoCfg }
    Start-Part 'desktop' $dtPy @('-m', 'impulse_guard.main') (Join-Path $root 'desktop') $dtEnv
}

if ($DryRun) { exit 0 }
if ($started.Count) { ($started | ConvertTo-Json) | Set-Content -Path $pidFile -Encoding ASCII }

# 4. 상태 확인 (최대 15초)
$web = $null; $ai = $null
for ($i = 0; $i -lt 15; $i++) {
    if (-not $web) { $web = Get-Url 'http://localhost:8001/' }
    if (-not $NoAi -and -not $ai) { $ai = Get-Url 'http://127.0.0.1:8002/health' }
    if ($web -and ($NoAi -or $ai)) { break }
    Start-Sleep -Seconds 1
}
Write-Host ''
Write-Host '상태'
Write-Host ("  웹 서버   http://localhost:8001      {0}" -f $(if ($web) { '응답함' } else { '응답 없음' }))
if (-not $NoAi) {
    if ($ai) {
        $h = $ai.Content | ConvertFrom-Json
        $risk = if ($h.services.risk) { "위험도 모델 $($h.services.risk.model)" } else { '위험도 모델 없음' }
        $msg  = if ($h.services.message) { "AI 요약 $($h.services.message.model)" } else { 'AI 요약 키 없음' }
        Write-Host "  예측 서버 http://127.0.0.1:8002/health  응답함 ($risk, $msg)"
    } else { Write-Host '  예측 서버 http://127.0.0.1:8002/health  응답 없음' }
}
Write-Host ("  모드      {0}" -f $(if ($Demo) { "시연 (예측 서버 위험도, 데모 회원$(if ($Llm) { ', AI 요약 버튼' }))" } else { '평소' }))
Write-Host '끄기: powershell -ExecutionPolicy Bypass -File scripts\stop.ps1'
