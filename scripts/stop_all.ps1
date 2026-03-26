# Legal Redaction - 停止本机相关端口上的服务
# 端口: HaS(8080) HaS Image(8081) OCR(8082) Backend(8000) Frontend(3000)

$ports = @(8080, 8081, 8082, 8000, 3000)

Write-Host ""
Write-Host "Legal Redaction - Stopping services on ports $($ports -join ', ')" -ForegroundColor Cyan
Write-Host ""

foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "Port $port : (no listener)" -ForegroundColor DarkGray
        continue
    }
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pids) {
        if (-not $procId -or $procId -eq 0) { continue }
        try {
            $p = Get-Process -Id $procId -ErrorAction Stop
            Write-Host "Port $port : stop PID $procId ($($p.ProcessName))" -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction Stop
        } catch {
            Write-Host "Port $port : could not stop PID $procId - $_" -ForegroundColor Red
        }
    }
}

Start-Sleep -Seconds 2
Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host ""
