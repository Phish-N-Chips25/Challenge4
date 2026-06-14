# Mata todos os processos do SentinelMAS que tenham ficado a correr.
#
# Uso:
#   .\kill.ps1
#
# Mata por duas vias:
#   1. Quem estiver a segurar as portas XMPP (5322 cliente / 5326 servidor)
#   2. Qualquer python a correr main.py / run_color.py / trigger.py

$ports   = 5322, 5326
$scripts = 'main.py', 'run_color.py', 'trigger.py'
$killed  = @{}

Write-Host "A procurar processos do SentinelMAS..." -ForegroundColor Cyan

# --- 1. Por porta XMPP ---
foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $procId = $c.OwningProcess
        if ($procId -and $procId -ne 0) { $killed[$procId] = "porta $port" }
    }
}

# --- 2. Por linha de comando (python a correr os scripts) ---
$pyProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue
foreach ($p in $pyProcs) {
    foreach ($s in $scripts) {
        if ($p.CommandLine -and $p.CommandLine -match [regex]::Escape($s)) {
            $killed[$p.ProcessId] = $s
            break
        }
    }
}

# --- Matar ---
if ($killed.Count -eq 0) {
    Write-Host "Nada a matar - nenhum processo do SentinelMAS encontrado." -ForegroundColor Green
} else {
    foreach ($procId in $killed.Keys) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "  morto  PID $procId  ($($killed[$procId]))" -ForegroundColor Yellow
        } catch {
            Write-Host "  falhou PID $procId  ($($killed[$procId])) - $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

# --- Confirmar portas livres ---
Start-Sleep -Milliseconds 800
$busy = Get-NetTCPConnection -LocalPort $ports -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "AVISO: portas ainda ocupadas:" -ForegroundColor Red
    $busy | Select-Object LocalPort, OwningProcess | Format-Table -AutoSize
} else {
    Write-Host "Portas 5322/5326 livres." -ForegroundColor Green
}
