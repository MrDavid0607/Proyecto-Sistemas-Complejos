# Manual del desarrollador — ComplexNet API

ComplexNet permite escribir aplicaciones descentralizadas en Python: cada computador ejecuta un
**nodo**, los nodos se descubren solos y la aplicación reparte su trabajo entre ellos con unas pocas
llamadas, sin servidor central.

## 1. Instalación

Requisitos: Python 3.10+.

```powershell
git clone https://github.com/MrDavid0607/Proyecto-Sistemas-Complejos.git
cd Proyecto-Sistemas-Complejos
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
$env:PYTHONPATH = "src"
```

Dependencias de ejecución: `psutil` y `numpy`. Para pruebas e informes: `pip install -r requirements-dev.txt`.

## 2. Primer programa

```python
from complexnet import Node, Task

with Node("nodo-01", port=9999, broadcast_address="auto") as node:   # connect() / disconnect()
    node.wait_for_peers(2)                       # espera a que se descubran 2 vecinos
    task = Task("regresion_lineal", {"n_samples": 10000, "seed": 42},
                requirements={"cpu": 1, "memory": 256})
    result = node.submit(task)                   # el planificador elige el nodo
    print(task.executed_by, result)
```

Los otros computadores solo ejecutan el nodo: `.\scripts\start_node.ps1 -Id nodo-02`
(ver [docs/TRES_PCS.md](../TRES_PCS.md)).

## 3. Referencia de la API

### `Node(node_id, config=None, **overrides)`

| Parámetro (`NodeConfig`) | Por defecto | Descripción |
|---|---|---|
| `port` | 9999 | puerto UDP del nodo |
| `broadcast_address` | `None` | dirección de broadcast de la subred; `"auto"` la detecta; `None` desactiva el broadcast |
| `seed_peers` | `[]` | lista de `(ip, puerto)` de vecinos conocidos (si el broadcast está bloqueado) |
| `ip_address` | detectada | IP de este equipo |
| `bandwidth_mbps` | 100 | ancho de banda que el nodo anuncia (valor declarado) |
| `slots` | 2 | tareas que el nodo ejecuta a la vez; el resto espera en cola |
| `strategy` | `weighted_load` | estrategia de asignación (ver §5) |
| `beacon_interval` | 2 s | período de los `RESOURCE_BEACON` |
| `node_timeout` | 5 s | silencio tras el cual un vecino se declara `OFFLINE` |
| `ack_timeout` | 5 s | espera del `TASK_ACK` antes de reasignar |
| `exec_timeout` | 60 s | tiempo máximo de ejecución antes de reasignar |
| `max_attempts` | 3 | intentos por tarea |
| `log_dir` | `None` | carpeta del log JSON del nodo |

| Método | Descripción |
|---|---|
| `connect()` / `disconnect()` | une el nodo a la red / lo detiene (también como `with Node(...) as n`) |
| `wait_for_peers(n, timeout=15)` | espera hasta tener `n` vecinos activos; devuelve `True/False` |
| `submit(task, allow_local=True, wait=True, timeout=None)` | envía una tarea. Con `wait=True` devuelve el resultado o lanza `TaskFailed`; con `wait=False` devuelve la `Task` |
| `map(name, params_list, requirements=None, allow_local=True, timeout=120)` | una tarea por elemento; devuelve los resultados **en orden** (lanza `TaskFailed` si alguna falla) |
| `map_tasks(...)` | igual que `map`, pero devuelve las `Task` (con `executed_by`, `reassignments`, tiempos...) |
| `broadcast(tipo, payload)` | envía un mensaje a todos los vecinos activos |
| `raise_alert(nivel, texto, **campos)` | registra una alerta y la difunde (`ALERT`) a toda la red |
| `on_event(callback)` | `callback(registro)` por cada evento del nodo (`TASK_COMPLETED`, `FAILURE`, ...) |
| `set_strategy(nombre)` | cambia la estrategia de asignación en caliente |
| `simulate_failure(segundos)` | el nodo deja de enviar y recibir (simula una caída; para pruebas) |
| `status()` | estado completo: recursos, vecinos, tareas, alertas, métricas |
| `peers` | `PeerTable` local: `peers.active()`, `peers.all()`, `peers.get(id)` |
| `metrics.snapshot()` | métricas del nodo (latencia, tiempos, tareas, tráfico...) |

### `Task(name, parameters=None, requirements=None, data=None)`

- `name`: tipo de tarea (ver §4).
- `parameters`: diccionario JSON-serializable. El mensaje completo debe ocupar **menos de 60 KB**.
- `requirements`: `{"cpu": % de CPU libre mínima, "memory": MB libres mínimos, "nodes": [ids permitidos]}`.
- Atributos tras el envío: `state` (`PENDING`, `ASSIGNED`, `RUNNING`, `COMPLETED`, `FAILED`), `result`,
  `error`, `executed_by`, `attempts`, `reassignments`, `wait(timeout)`.

### Errores

- `TaskFailed`: la tarea terminó en `FAILED` (sin nodos aptos, reintentos agotados o error de ejecución).
- `TimeoutError`: `submit(..., timeout=N)` no terminó a tiempo.

## 4. Tipos de tarea disponibles

| Nombre | Parámetros principales | Resultado |
|---|---|---|
| `regresion_lineal` | `n_samples`, `seed`, `true_slope`, `true_intercept`, `noise`, `epochs`, `learning_rate` | `slope`, `intercept`, `mse`, `r2` |
| `normal_equations` | `shard`, `n_samples`, `n_features`, `model_seed`, `data_seed`, `noise` | `xtx`, `xty`, `n`, `sum_y`, `sum_yy` (regresión por fragmentos) |
| `evaluate_model` | los de `normal_equations` + `weights` | `sse`, `sst`, `mse`, `r2` |
| `monte_carlo_pi` | `n_points`, `seed` | `inside`, `total` |
| `word_count` | `text`, `top` | `counts`, `words` |
| `echo` | cualquiera | los mismos parámetros |

Cualquier tarea acepta `simulate_seconds` para alargarla artificialmente (pruebas de fallo).

### Añadir una tarea nueva

En `src/complexnet/tasks/executors.py`, escribe una función `def mi_tarea(parameters): ... return dict` y
regístrala en `EXECUTORS`. Todos los nodos deben tener esa versión del código.

## 5. Estrategias de asignación

| Nombre | Descripción |
|---|---|
| `weighted` | función de aptitud F(i,j) del diseño (CPU 0.40, memoria 0.40, ancho de banda 0.10, reputación 0.05, latencia −0.05), normalización min-max |
| `weighted_load` | (por defecto) F(i,j) con un término de carga actual (peso 0.30) y normalización robusta (rango mínimo significativo) |
| `least_loaded` | el nodo con menos tareas en curso |
| `lowest_latency` | el nodo con menor latencia medida |
| `round_robin` | reparto cíclico |
| `random` | al azar |

El detalle del modelo está en `docs/arquitectura/ARQUITECTURA.md` y la comparación experimental en
`docs/pruebas/INFORME_EXPERIMENTAL.md`.

## 6. Patrón map-reduce

```python
from collections import Counter
chunks = [texto[i:i + 6000] for i in range(0, len(texto), 6000)]
tasks = node.map_tasks("word_count", [{"text": c} for c in chunks])      # map (repartido en la red)
total = Counter()
for t in tasks:                                                           # reduce (local)
    total.update(t.result["counts"])
```

Si un nodo cae durante el `map`, sus fragmentos se reasignan automáticamente y el resultado no cambia.

## 7. Monitoreo y alertas

- Panel web de cada nodo (`--http-port`, por defecto 8000): `http://IP:8000`.
- API HTTP: `GET /status`, `GET /events`, `GET /tasks/<id>`, `POST /tasks`, `POST /admin/fail`, `POST /admin/strategy`.
- Alertas distribuidas: `node.raise_alert("warning", "texto")` llega al registro de alertas de todos los nodos.
- Log JSON por nodo en `log_dir`, con el reloj de Lamport de cada evento.

## 8. Ejecutar un nodo desde la línea de comandos

```powershell
python -m complexnet --id nodo-02 --broadcast auto --http-port 8000
python -m complexnet --id nodo-02 --peers 192.168.1.5,192.168.1.7      # sin broadcast
```

Opciones: `--port`, `--ip`, `--peers`, `--broadcast`, `--bandwidth`, `--slots`, `--strategy`, `--timeout`,
`--http-port`, `--log-dir`. También se leen de variables de entorno (`NODE_ID`, `SEED_PEERS`, ...).

## 9. Arquitectura en una vista

```
Aplicación  ──►  Node (API)  ──►  TaskManager ──► DistributedScheduler (estrategia)
                    │                  │
                    │                  └─► UDP: TASK_SUBMIT / TASK_ACK / TASK_RESULT
                    ├─► DiscoveryService (RESOURCE_BEACON, PING/PONG) ──► PeerTable
                    ├─► FailureDetector (5 s) ──► RecoveryManager ──► reasigna tareas
                    ├─► LamportClock · EventLogger · Metrics · StatusServer (HTTP)
                    └─► ICommunicationLayer ──► UDPCommunication (JSON)
```

## 10. Limitaciones conocidas

- Mensajes UDP de hasta 60 KB; no hay fragmentación ni retransmisión (se compensa con ACK, timeout y reasignación).
- El ancho de banda es declarativo.
- El nodo que envía una tarea es quien la coordina: si cae, pierde el estado de sus tareas.
- Los endpoints `/admin` no tienen autenticación (uso de laboratorio).
