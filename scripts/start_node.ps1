<#
  Arranca un nodo ComplexNet en este computador (Windows).

  Uso (PowerShell, en la carpeta del repositorio):
      .\scripts\start_node.ps1 -Id nodo-02
      .\scripts\start_node.ps1 -Id nodo-02 -Peers 192.168.1.5,192.168.1.7   # si el broadcast no funciona

  La primera vez crea el entorno virtual, instala las dependencias y abre el firewall
  (pide permisos de administrador una sola vez).
#>
param(
    [Parameter(Mandatory = $true)][string]$Id,
    [string]$Peers = "",
    [int]$Port = 9999,
    [int]$HttpPort = 8000,
    [double]$Bandwidth = 100,
    [string]$Strategy = "weighted_load",
    [string]$Ip = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1) Entorno virtual y dependencias
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creando entorno virtual..." -ForegroundColor Cyan
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -c "import psutil, numpy" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando dependencias..." -ForegroundColor Cyan
    & .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
}

# 2) Firewall: UDP del nodo y TCP del panel web
$rule = "ComplexNet"
if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
               ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $cmd = "New-NetFirewallRule -DisplayName '$rule' -Direction Inbound -Action Allow -Protocol UDP -LocalPort $Port -Profile Any | Out-Null; " +
           "New-NetFirewallRule -DisplayName '$rule' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $HttpPort -Profile Any | Out-Null"
    Write-Host "Abriendo el firewall para ComplexNet (UDP $Port, TCP $HttpPort)..." -ForegroundColor Cyan
    if ($isAdmin) { Invoke-Expression $cmd }
    else { Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile", "-Command", $cmd }
}

# 3) Mostrar la IP y arrancar
$ipArg = @()
if ($Ip -ne "") { $ipArg = @("--ip", $Ip) }
$detected = & .\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); from complexnet.node import get_local_ip; print(get_local_ip())"
Write-Host ""
Write-Host "Nodo: $Id | IP detectada: $detected | Panel: http://localhost:$HttpPort" -ForegroundColor Green
Write-Host "Ctrl+C para detenerlo." -ForegroundColor Green
Write-Host ""

$peersArg = @()
if ($Peers -ne "") { $peersArg = @("--peers", $Peers) }   # un argumento vacío se pierde en PowerShell

$env:PYTHONPATH = "src"
& .\.venv\Scripts\python.exe -m complexnet --id $Id --port $Port --broadcast auto @peersArg `
    --http-port $HttpPort --bandwidth $Bandwidth --strategy $Strategy --log-dir logs @ipArg
