# Pruebas — Fase 2

```bash
python -m pytest tests -v        # 42 pruebas, ~25 s
```

## Unitarias (`tests/test_scheduler.py`, `tests/test_components.py`)

| Área | Qué se verifica |
|---|---|
| Planificador | Pesos suman 1; normalización directa e inversa; valores iguales; **ejemplo numérico del diseño** (F ≈ 0.46 / 0.54 / 0.39 → gana N2); filtrado por disponibilidad, CPU y memoria; sin candidatos; desempate por latencia y reputación |
| Mensajes | Ida y vuelta JSON; formato `header`/`payload`; rechazo de mensajes inválidos; `message_id` únicos; UDP entrega y descarta duplicados |
| Lamport | `tick`, `update`, causalidad (recepción > envío) |
| PeerTable | Alta, actualización, `OFFLINE` y reincorporación; expiración por timeout; latencia con media móvil; reputación acotada a [0, 1] |
| Detector de fallos | Marca `OFFLINE` y notifica una sola vez; respeta el umbral de 5 s (exactamente 5 s no es fallo) |
| Ejecutores (IA) | La regresión recupera pendiente e intercepto; reproducible por semilla; descenso de gradiente converge; tarea desconocida falla |
| Logger y métricas | JSONL con Lamport; cálculo de tasa de fallos y promedios |

## Integración (`tests/test_integration.py`)

Tres nodos reales (sockets UDP en localhost, hilos independientes), con tiempos reducidos
(beacon 0.3 s, timeout 1.5 s) para que la prueba sea rápida.

| Escenario del taller | Prueba |
|---|---|
| Operación normal | Descubrimiento de 3 nodos mediante beacons unicast a vecinos semilla (el broadcast se usa en Docker); medición de latencia; ejecución de una tarea de ML en otro nodo con resultado correcto |
| Desconexión de un nodo durante una tarea | La tarea se reasigna al nodo restante y termina `COMPLETED` (`reassignments ≥ 1`, `failures_detected ≥ 1`, tiempo de recuperación medido) |
| Entrada de un nuevo nodo | Un nodo caído vuelve con el mismo ID y pasa de `OFFLINE` a `ONLINE` |
| Sin recursos | Una tarea sin candidatos aptos queda en cola y falla al agotar el tiempo de espera |
| Sincronización | Los relojes de Lamport avanzan con la comunicación |

## Validación con procesos independientes

Además de las pruebas en proceso, se ejecutaron 3 procesos del sistema operativo
(`python -m complexnet ...`, uno por nodo) con los tiempos reales (beacon 2 s, timeout 5 s):

- Descubrimiento mutuo en < 0.1 s con semillas.
- 4 tareas de regresión lineal (20 000 muestras) completadas, pendiente ≈ 2.35.
- Tarea de 12 s: al terminar el proceso ejecutor se detectó el fallo, se reasignó a otro nodo
  y se completó (`ASSIGNED:nodo-03 > REASSIGN:nodo-03 > ASSIGNED:nodo-02 > COMPLETED:nodo-02`).

## Métricas medidas

Resultado de la corrida anterior en `nodo-01` (red local, sin carga adicional):

| Métrica | Valor |
|---|---|
| Latencia media de comunicación | ≈ 0.7 ms |
| Tiempo de descubrimiento | < 0.01 s |
| Tiempo de asignación (decisión del planificador) | ≈ 0.04 ms |
| Tareas completadas / reasignadas / fallidas | 5 / 1 / 0 |
| Fallos detectados | 1 |
| Tiempo de recuperación | ≈ 12 s (incluye volver a ejecutar la tarea simulada de 12 s) |

El tiempo de recuperación se mide desde la primera reasignación hasta que la tarea termina;
la detección en sí tarda como máximo `T_timeout = 5 s`.

## Limitaciones de las pruebas

- Las pruebas de integración corren en una sola máquina; el tiempo de descubrimiento y la
  latencia sobre Docker o una red real serán mayores.
- No se midió consumo de ancho de banda real (el ancho de banda es declarativo) ni el
  comportamiento con pérdida de paquetes.
