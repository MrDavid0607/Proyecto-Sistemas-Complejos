# Arquitectura implementada — ComplexNet API (Fase 2)

Este documento describe lo que **realmente está implementado** en `src/complexnet/`
y cómo se relaciona con el diseño de la Fase 1 (UML, modelo de asignación y
protocolo de descubrimiento).

## 1. Vista por capas

```
Aplicaciones descentralizadas        (Fase 3)
API de alto nivel                    Node.connect() / submit() / broadcast()   node.py
Servicios distribuidos               discovery · resources · scheduler · tasks ·
                                     failure_detection · synchronization · monitoring
Comunicación y serialización         communication/  (UDP + JSON, interfaz abstracta)
Infraestructura                      Docker (3 contenedores en una red bridge)
```

## 2. Módulos y su correspondencia con el diseño

| Componente del diseño | Módulo | Clase principal |
|---|---|---|
| Node Discovery / `TablaPares` | `discovery/` | `DiscoveryService`, `PeerTable` |
| Resource Manager / `GestorRecursos` | `resources/` | `ResourceManager` |
| Message Service / `ICapaComunicacion` | `communication/` | `ICommunicationLayer`, `UDPCommunication`, `Message` |
| Distributed Scheduler / `PlanificadorDistribuido` | `scheduler/` | `DistributedScheduler` |
| Task Manager / `GestorTareas` | `tasks/` | `TaskManager`, `Task` |
| Failure Detector / `DetectorFallos` | `failure_detection/` | `FailureDetector` |
| Recovery Manager / `GestorRecuperacion` | `tasks/recovery.py` | `RecoveryManager` |
| Synchronization Service | `synchronization/` | `LamportClock` |
| Logger and Monitor | `monitoring/` | `EventLogger`, `Metrics`, `TerminalMonitor`, `StatusServer` |
| Developer API / `Nodo` | `node.py` | `Node`, `NodeConfig` |

`ICommunicationLayer` desacopla el transporte de la lógica (requisito no funcional de
modularidad): ningún servicio usa sockets directamente.

## 3. Mensajes

Todos los mensajes son JSON con `header` y `payload`:

```json
{
  "header": {"message_id": "uuid-v4", "sender_id": "nodo-01",
             "type": "TASK_SUBMIT", "timestamp": 1789010342069, "lamport": 17},
  "payload": {}
}
```

| Tipo | Dirección | Payload |
|---|---|---|
| `RESOURCE_BEACON` | broadcast (+ unicast a semillas) cada 2 s | `ip_address, port, cpu_free_pct, ram_free_mb, bandwidth_mbps, active_tasks` |
| `PING` / `PONG` | unicast | `sent_at` (para medir la latencia, RTT) |
| `TASK_SUBMIT` | unicast, emisor → ejecutor | `task_id, task_name, parameters, requirements` |
| `TASK_ACK` | unicast, ejecutor → emisor | `task_id` |
| `TASK_RESULT` | unicast, ejecutor → emisor | `task_id, status, execution_time_sec, result_data` o `error` |

Se añadió `lamport` al header respecto al diseño original. Cada nodo descarta
mensajes con un `message_id` ya visto.

## 4. Descubrimiento y detección de fallos

1. Cada nodo emite un `RESOURCE_BEACON` cada 2 s por UDP broadcast (en Docker, a la
   dirección de broadcast de la subred `172.30.77.255`).
2. Al recibir un beacon de un nodo desconocido lo registra en su `PeerTable`
   (estado `ONLINE`) y mide su latencia con `PING/PONG`.
3. El `FailureDetector` revisa cada 0.5 s: si `t_actual − last_seen > 5 s` el
   vecino pasa a `OFFLINE` y se notifica al `RecoveryManager`.
4. Si el nodo vuelve a emitir beacons se marca `ONLINE` (evento `RECOVERY`).

Cualquier mensaje recibido de un vecino renueva su `last_seen`.

## 5. Planificador

Implementa exactamente el modelo de la sección 9 del diseño:

- `V_cand = { i | A_i ∧ C_i ≥ C_req ∧ M_i ≥ M_req }`
- Normalización min-max sobre los candidatos; la latencia con normalización inversa.
- `F(i,j) = 0.40·C' + 0.40·M' + 0.10·B' + 0.05·R − 0.05·(1 − L')`
- `i* = argmax F`; empate → menor latencia → mayor reputación.
- Sin candidatos: la tarea queda `PENDING` y se reintenta cada segundo.

Decisiones de implementación:

- **Tarea.** `requirements = {"cpu": % libre mínimo, "memory": MB libres mínimos}`.
- **Ancho de banda (B).** No se mide: es un valor declarado por nodo (`BANDWIDTH_MBPS`).
- **Latencia (L).** Se mide como RTT con `PING/PONG` y se suaviza con media móvil exponencial (α = 0.3).
- **Reputación (R).** Cada nodo mantiene la reputación de sus vecinos, en [0, 1]. Empieza en 1.0, suma +0.05 por tarea exitosa y resta 0.20 por fallo o timeout.
- **Valores iguales.** Si todos los candidatos tienen el mismo valor en una métrica, esa métrica normalizada vale 1 para todos (sin penalización ni ventaja).
- **Nodo local.** El propio nodo es candidato (con latencia 0) salvo que se envíe con `allow_local=False`.

## 6. Ciclo de vida de una tarea

```
PENDING ──(planificador elige nodo)──► ASSIGNED ──TASK_ACK──► RUNNING ──TASK_RESULT──► COMPLETED
   ▲                                       │                      │
   └──── reasignación (excluye al nodo) ◄──┴──────────────────────┘      FAILED: reintentos agotados
```

Una tarea se **reasigna** a otro nodo cuando:

1. el ejecutor no responde con `TASK_ACK` en 5 s,
2. el `FailureDetector` marca `OFFLINE` al ejecutor,
3. el ejecutor devuelve `status = FAILED`, o
4. se supera el tiempo máximo de ejecución (60 s por defecto).

El nodo excluido no vuelve a considerarse para esa tarea. Máximo 3 intentos.
El **tiempo de recuperación** es el tiempo entre la primera reasignación y la
finalización de la tarea.

## 7. Tarea de IA

`regresion_lineal`: regresión lineal por mínimos cuadrados (o descenso de gradiente
con `epochs` y `learning_rate`) sobre datos sintéticos generados en el propio
nodo con una semilla (`seed`, `n_samples`, `true_slope`, `true_intercept`, `noise`).
Devuelve `slope, intercept, mse, r2`. Cada nodo reproduce su porción del dataset
sin transferirlo por la red. `simulate_seconds` alarga la tarea para emular un
entrenamiento pesado en las pruebas de fallo.

## 8. Sincronización

Reloj lógico de Lamport en cada nodo. Se incrementa en cada envío y se ajusta con
`max(local, recibido) + 1` en cada recepción. Aparece en cada mensaje y en cada línea
del log, de modo que los logs de varios nodos se pueden ordenar causalmente.

## 9. Registro y monitoreo

- **Log JSON por nodo** (`logs/<nodo>.jsonl`) con `ts`, `lamport`, `node`, `event`.
- **Eventos:** `NODE_STARTED, DISCOVERY, RECOVERY, FAILURE, TASK_CREATED, TASK_ASSIGNED,
  TASK_ACK, TASK_RUNNING, TASK_COMPLETED, TASK_REASSIGN, TASK_FAILED, TASK_QUEUED`.
- **Métricas:** latencia media, tiempo de descubrimiento, tiempo de asignación,
  tiempo de ejecución, tiempo total, tiempo de recuperación, tareas enviadas,
  completadas, fallidas y reasignadas, tasa de fallos y mensajes enviados.
- **Monitor en terminal** (cada 10 s) y **panel HTTP** por nodo (`/`, `/status`,
  `/events`, `/tasks/<id>`, `POST /tasks`).

## 10. Limitaciones conocidas

- Las tareas viajan por UDP sin retransmisión: la pérdida de un datagrama se maneja con
  el timeout de `ACK` y la reasignación, no con reenvío. Los mensajes son pequeños.
- El ancho de banda es declarativo.
- La sincronización es un orden lógico de eventos, sin exclusión mutua distribuida.
- No hay persistencia: si el nodo emisor cae, pierde el estado de sus tareas.
