<#
  impulse-guard 한 번에 끄기 (7 마무리)

  scripts\start.ps1이 켜서 data\ipp_pids.json에 적은 프로세스(웹 서버, 예측 서버, 데스크톱)만 끈다.
  직접 켠 서버는 끄지 않고, 8001·8002 포트를 쓰는 프로세스를 알려 주기만 한다.

  사용 (저장소 루트에서): powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
#>
$root    = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root 'data\ipp_pids.json'

if (Test-Path $pidFile) {
    $list = Get-Content $pidFile -Raw | ConvertFrom-Json
    foreach ($prop in $list.PSObject.Properties) {
        $p = Get-Process -Id $prop.Value -ErrorAction SilentlyContinue
        if ($p) {
            # 데스크톱(python)은 자식 프로세스가 없고, php -S와 uvicorn도 한 프로세스라 그 프로세스만 끈다
            Stop-Process -Id $prop.Value -Force -ErrorAction SilentlyContinue
            Write-Host "$($prop.Name) 끔 (프로세스 $($prop.Value))"
        } else {
            Write-Host "$($prop.Name) 이미 꺼져 있음 (프로세스 $($prop.Value))"
        }
    }
    Remove-Item $pidFile -Force
} else {
    Write-Host 'start.ps1로 켠 기록(data\ipp_pids.json)이 없습니다.'
}

foreach ($port in 8001, 8002) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { Write-Host "참고: $port 포트를 프로세스 $($c.OwningProcess)가 아직 쓰고 있습니다 (직접 켠 서버라면 그 창에서 Ctrl+C)." }
}
