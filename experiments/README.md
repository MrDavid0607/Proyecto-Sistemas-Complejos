# Experimentos de la Fase 3

Miden latencia, tiempo de descubrimiento, escalabilidad (más nodos y más carga), comparación
de estrategias de asignación, tolerancia a fallos y disponibilidad.

## Con los 3 computadores

1. Los computadores 2 y 3 corren su nodo (`scripts/start_node.ps1 -Id nodo-02` / `nodo-03`).
   **Dejar el panel en el puerto 8000**: el experimento lo usa para simular caídas de esos nodos.
2. En el computador 1 (sin tener corriendo su propio nodo):

```powershell
.\.venv\Scripts\python.exe experiments\run_experiments.py --id nodo-01 --http-port 0
```

   Si el broadcast está bloqueado: `--peers IP-NODO-02,IP-NODO-03`.
   Duración: ≈ 10–12 minutos (versión completa). Prueba rápida: añadir `--quick` (≈ 3 min).

3. Generar el informe:

```powershell
.\.venv\Scripts\python.exe experiments\report.py
```

   Crea `docs/pruebas/INFORME_EXPERIMENTAL.md` y las gráficas en `docs/pruebas/figuras/`. También
   actualiza `docs/informe/fase3_resultados.tex` (tablas y figuras en LaTeX para la sección 12 del
   informe del proyecto; ver `docs/informe/LEEME.md`).

Opciones útiles: `--only strategies,fault` (solo algunos experimentos), `--task-points N`
(duración de cada tarea) y `--environment "texto"` (descripción del entorno para el informe).

## En un solo computador (prueba)

Tres procesos en `localhost` con puertos distintos (nodo-02: 9302 y panel 8302, nodo-03: 9303 y panel 8303):

```powershell
.\scripts\local_cluster.ps1          # arranca nodo-02 y nodo-03 en segundo plano
.\.venv\Scripts\python.exe experiments\run_experiments.py --id nodo-01 --port 9301 --ip 127.0.0.1 --broadcast none --peers 127.0.0.1:9302,127.0.0.1:9303 --http-port 0 --admin-ports nodo-02=8302,nodo-03=8303 --probe-port 9970 --environment "1 PC (3 procesos en localhost)"
```

## Los experimentos

| Experimento | Qué hace | Salida |
|---|---|---|
| `latency` | RTT de `PING/PONG` y de una tarea mínima a cada nodo | `latency.csv` |
| `discovery` | Arranca nodos sonda y mide cuánto tardan en ver a todos | `discovery.csv` |
| `scalability` | Mismo lote con 1, 2 y 3 nodos; carga de 4 a 64 tareas | `scalability_*.csv` |
| `strategies` | Las 6 estrategias sobre el mismo lote heterogéneo | `strategies.csv` |
| `fault` | Un nodo cae durante un lote: detección, reasignación, recuperación | `fault_tolerance.csv` |
| `availability` | Sondas cada 0.5 s mientras un nodo falla | `availability.csv` |

Las fallas se inyectan con `POST /admin/fail` en el panel HTTP del nodo víctima: el nodo deja de
enviar y recibir mensajes durante N segundos (equivale a perder la red).
