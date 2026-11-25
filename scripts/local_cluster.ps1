<#
  Prueba en un solo computador: arranca nodo-02 y nodo-03 como procesos en segundo plano
  (puertos UDP 9302/9303, paneles 8302/8303). nodo-01 es el proceso que tú ejecutas
  (puerto 9301). Para detenerlos:  .\scripts\local_cluster.ps1 -Stop
#>
param([switch]$Stop)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"

if ($Stop) {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "complexnet --id nodo-0[23]" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "Nodos locales detenidos."
    return
}

$env:PYTHONPATH = "src"
$nodes = @(@("nodo-02", 9302, 8302, 50), @("nodo-03", 9303, 8303, 200))
foreach ($n in $nodes) {
    $peers = "127.0.0.1:9301," + (($nodes | Where-Object { $_[0] -ne $n[0] } | ForEach-Object { "127.0.0.1:$($_[1])" }) -join ",")
    Start-Process -WindowStyle Hidden -FilePath $py -ArgumentList @(
        "-m", "complexnet", "--id", $n[0], "--port", $n[1], "--http-port", $n[2],
        "--bandwidth", $n[3], "--peers", $peers, "--ip", "127.0.0.1") `
        -RedirectStandardOutput "$env:TEMP\$($n[0]).out" -RedirectStandardError "$env:TEMP\$($n[0]).err"
}
Write-Host "nodo-02 (UDP 9302, panel http://localhost:8302) y nodo-03 (UDP 9303, panel http://localhost:8303) en marcha."
