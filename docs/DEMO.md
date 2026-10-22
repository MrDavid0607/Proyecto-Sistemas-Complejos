# Guion de demostración (video de la Fase 2)

Duración sugerida: 6–8 minutos. Terminales: una para `docker compose logs -f`, otra para los comandos.

## 0. Preparación

```bash
docker compose up --build -d
docker compose ps
```

Muestra los 3 contenedores (`complexnet-nodo-01..03`) en la red `complexnet-net` (172.30.77.0/24).
Abre el panel de un nodo: <http://localhost:8001> (nodo-02: 8002, nodo-03: 8003).

## 1. Descubrimiento automático (sin coordinador)

```bash
docker compose logs nodo-01 | findstr DISCOVERY
```

Cada nodo descubrió a los otros dos por UDP broadcast. En el panel se ve la `PeerTable` con
CPU, RAM, ancho de banda, latencia y reputación.

## 2. Operación normal: asignación de tareas de IA

```bash
python scripts/demo.py normal
```

Cinco regresiones lineales enviadas a nodo-01 con `allow_local=false`. El planificador evalúa
`F(i,j)` y elige ejecutor; el log muestra `TASK_ASSIGNED … score=…`. Explica el puntaje con la
fórmula del diseño (CPU y RAM pesan 80 %).

## 3. Incremento de carga

```bash
python scripts/demo.py carga
```

Lotes de 2, 6 y 12 tareas. Se muestra el tiempo total y qué nodos las ejecutaron.

## 4. Un nodo cae durante una tarea (tolerancia a fallos)

```bash
python scripts/demo.py fallo
```

1. Se lanza una tarea larga (20 s) y se ve a qué nodo se asignó.
2. Se detiene ese contenedor (`docker stop`).
3. A los 5 s el log del emisor muestra `FAILURE … OFFLINE` y `TASK_REASSIGN`.
4. La tarea termina en otro nodo (`TASK_COMPLETED … attempts=2`).
5. Se reinicia el contenedor y aparece `RECOVERY`.

## 5. Salida y entrada de un nodo

```bash
python scripts/demo.py ingreso
```

Muestra `ONLINE → OFFLINE → ONLINE` en la PeerTable de nodo-01.

## 6. Registro de eventos y sincronización

```bash
type logs\nodo-01.jsonl
```

Cada evento lleva el reloj de Lamport. Al unir los logs de los 3 nodos y ordenar por
`lamport` se obtiene el orden causal de la ejecución.

## 7. Métricas

<http://localhost:8001/status> → `metrics`: latencia media, tiempo de asignación, tiempo de
recuperación, tareas completadas/reasignadas, tasa de fallos.

## 8. Pruebas automáticas

```bash
python -m pytest tests -v
```

## Cierre

```bash
docker compose down
```
