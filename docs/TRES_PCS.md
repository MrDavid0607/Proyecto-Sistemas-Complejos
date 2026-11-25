# Ejecución en 3 computadores

La red real tiene tres computadores en la **misma red local** (mismo Wi-Fi o hotspot).
Cada uno ejecuta un nodo de ComplexNet. No hay servidor central.

| PC | Nodo | Qué corre |
|---|---|---|
| PC 1 (David) | `nodo-01` | un nodo + las aplicaciones y los experimentos |
| PC 2 | `nodo-02` | solo el nodo |
| PC 3 | `nodo-03` | solo el nodo |

## Mensaje para tus compañeros (copiar y pegar)

> Hola. Necesito que corran un nodo en su PC para la demo del proyecto. Pasos (Windows):
>
> 1. Tener **Python 3.10 o superior** y **Git** instalados (`python --version`).
> 2. Conectarse al **mismo Wi-Fi** que yo: `NOMBRE-DEL-WIFI`.
> 3. Abrir PowerShell y ejecutar:
>
> ```powershell
> git clone https://github.com/MrDavid0607/Proyecto-Sistemas-Complejos.git
> cd Proyecto-Sistemas-Complejos
> Set-ExecutionPolicy -Scope Process Bypass
> .\scripts\start_node.ps1 -Id nodo-02
> ```
>
> (el segundo compañero usa `-Id nodo-03`). La primera vez instala dependencias y pide
> permiso de administrador para abrir el firewall: aceptar.
> 4. Dejar la ventana abierta. Debe mostrar `NODE_STARTED` y, en unos segundos, `DISCOVERY`
> con los otros nodos. Avísenme su **IP** (la imprime al arrancar).
> 5. Para cerrar: `Ctrl+C`.
>
> Si ya tienen el repo: `git pull` antes de correrlo.

Linux/macOS: `./scripts/start_node.sh nodo-02`.

## Arranque en tu PC (nodo-01)

```powershell
.\scripts\start_node.ps1 -Id nodo-01
```

Abre el panel en el navegador: <http://localhost:8000>. Allí se ven los 3 computadores,
su CPU, RAM, latencia, las tareas y las alertas.

## Si los nodos no se descubren

El descubrimiento usa UDP broadcast. Algunas redes (Wi-Fi de universidades, redes de invitados)
aíslan a los clientes y lo bloquean. Soluciones, de la más simple a la más segura:

1. **Pasar las IPs a mano** (funciona aunque se bloquee el broadcast, pero no el aislamiento de clientes):
   ```powershell
   .\scripts\start_node.ps1 -Id nodo-02 -Peers 192.168.1.5,192.168.1.7
   ```
   con las IPs de los otros dos computadores.
2. **Usar el hotspot de un celular** al que se conecten los tres PCs. Es lo más fiable.
3. Revisar el **firewall**: el script abre UDP 9999 y TCP 8000. Si falló, abrir PowerShell como administrador y ejecutar:
   ```powershell
   New-NetFirewallRule -DisplayName ComplexNet -Direction Inbound -Action Allow -Protocol UDP -LocalPort 9999 -Profile Any
   New-NetFirewallRule -DisplayName ComplexNet -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Any
   ```
4. Verificar conectividad: `ping IP-DEL-OTRO-PC`.

## Verificar que la red está formada

En cada PC, la consola debe mostrar:

```
[..] nodo-02 DISCOVERY peer=nodo-01 address=192.168.1.5:9999 ...
[..] nodo-02 DISCOVERY peer=nodo-03 address=192.168.1.7:9999 ...
```

Y en el panel (<http://localhost:8000>) deben aparecer los otros dos nodos en `ONLINE`.

## Correr las aplicaciones (solo en la PC 1)

Las aplicaciones **son** el nodo de la PC 1: no hay que correr `start_node.ps1` a la vez en esa PC
(usan el mismo puerto). Con los nodos 02 y 03 ya arrancados:

```powershell
.\.venv\Scripts\python.exe applications\monitoring_app\app.py --id nodo-01
.\.venv\Scripts\python.exe applications\distributed_processing\app.py --id nodo-01 --no-local
.\.venv\Scripts\python.exe applications\ai_application\app.py --id nodo-01 --no-local
```

`--no-local` hace que todo el trabajo se ejecute en los otros dos computadores. Quítalo para usar
también la PC 1. Si el broadcast está bloqueado, añade `--peers IP-NODO-02,IP-NODO-03`.

Los experimentos (ver `experiments/README.md`) se lanzan igual, también desde la PC 1.
