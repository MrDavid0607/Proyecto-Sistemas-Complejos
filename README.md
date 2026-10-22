# ComplexNet API

Proyecto integrador de la asignatura **Sistemas Complejos**.

ComplexNet API propone una arquitectura para computación descentralizada sobre redes Ad hoc, en la cual diferentes nodos pueden descubrirse, intercambiar información y mantener una visión local de los participantes activos de la red.

## Fase 2 - Núcleo funcional (segundo corte)

El núcleo vive en `src/complexnet/` y se ejecuta como una red de nodos autónomos, sin coordinador central:

| Servicio | Módulo |
|---|---|
| Descubrimiento de nodos y `PeerTable` | `discovery/` |
| Registro de recursos (CPU, RAM, ancho de banda, latencia, reputación) | `resources/`, `discovery/` |
| Mensajería (UDP + JSON, interfaz abstracta) | `communication/` |
| Planificador distribuido `F(i,j)` | `scheduler/` |
| Gestión de tareas, ejecución de IA y reasignación | `tasks/` |
| Detección de fallos (timeout 5 s) | `failure_detection/` |
| Sincronización (reloj de Lamport) | `synchronization/` |
| Registro de eventos, métricas y monitoreo | `monitoring/` |
| API de alto nivel | `node.py` (`Node`, `Task`) |

La tarea de IA es una regresión lineal que cada nodo ejecuta sobre datos sintéticos generados con una semilla.
Documentación: [arquitectura implementada](docs/arquitectura/ARQUITECTURA.md), [pruebas](docs/pruebas/PRUEBAS.md) y [guion de demostración](docs/DEMO.md).

### Uso rápido (sin Docker)

```powershell
pip install -r requirements.txt
$env:PYTHONPATH = "src"
python examples/basic_usage.py      # 3 nodos en localhost y una tarea de ML
python -m pytest tests -v           # 42 pruebas unitarias y de integración
```

```python
from complexnet import Node, Task

node = Node("nodo-01").connect()
result = node.submit(Task("regresion_lineal", {"n_samples": 10000},
                          requirements={"cpu": 1, "memory": 256}))
```

### Red de 3 nodos con Docker

```bash
docker compose up --build -d          # nodo-01, nodo-02, nodo-03 en 172.30.77.0/24
python scripts/demo.py todo           # operación normal, carga, fallo e ingreso de nodos
docker compose down
```

Panel de cada nodo: <http://localhost:8001>, <http://localhost:8002> y <http://localhost:8003>.
Los logs JSON de cada nodo quedan en `logs/`.

## Prueba de concepto - Primer corte

Para el primer corte se implementó una prueba de concepto inicial de comunicación entre dos nodos.

La implementación permite demostrar:

- Comunicación entre dos nodos independientes.
- Descubrimiento automático de nodos.
- Intercambio periódico de mensajes `RESOURCE_BEACON`.
- Registro de nodos en una `PeerTable` local.
- Publicación de recursos disponibles de CPU y memoria RAM.
- Detección de nodos inactivos mediante timeout.
- Reincorporación automática de un nodo después de una desconexión.

## Tecnologías utilizadas

- Python 3
- UDP sockets
- JSON
- Threading
- psutil

## Estructura del proyecto

```text
complexnet-api/
│
├── src/
│   └── proof_of_concept/
│       └── node.py
│
├── requirements.txt
├── README.md
└── .gitignore
```

## Instalación

Se recomienda utilizar un entorno virtual de Python.

### 1. Crear el entorno virtual

En Windows:

```powershell
python -m venv .venv
```

### 2. Activar el entorno virtual

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Instalar dependencias

```powershell
pip install -r requirements.txt
```

## Ejecución de la prueba local

La prueba puede realizarse utilizando dos procesos independientes en el mismo computador.

Cada proceso representa un nodo lógico de ComplexNet y utiliza un puerto UDP diferente.

### Nodo 1

Abrir una terminal y ejecutar:

```powershell
python src/proof_of_concept/node.py --id nodo-01 --port 9999 --peer-port 10000 --local-test
```

### Nodo 2

Abrir una segunda terminal y ejecutar:

```powershell
python src/proof_of_concept/node.py --id nodo-02 --port 10000 --peer-port 9999 --local-test
```

## Descubrimiento de nodos

Cuando ambos procesos están activos, cada nodo envía un mensaje `RESOURCE_BEACON` cada 2 segundos.

Al recibir un beacon de un nodo desconocido, este se registra automáticamente en la `PeerTable`.

Ejemplo:

```text
[DISCOVERY] Nuevo nodo descubierto
Node ID: nodo-02
IP: 127.0.0.1
Puerto: 10000
Estado: ONLINE
```

La tabla de vecinos muestra el estado y los recursos reportados por el nodo:

```text
========== PEER TABLE ==========
nodo-02 | 127.0.0.1:10000 | ONLINE | CPU libre: 90.8% | RAM libre: 2486.05 MB
================================
```

## Detección de fallos

Los nodos envían un `RESOURCE_BEACON` cada 2 segundos.

Si un nodo deja de recibir mensajes de otro nodo durante más de 5 segundos, este cambia su estado de `ONLINE` a `OFFLINE`.

Ejemplo:

```text
[FAILURE] nodo-02 no responde desde hace más de 5 segundos.
Estado: OFFLINE
```

La `PeerTable` también refleja el cambio:

```text
nodo-02 | 127.0.0.1:10000 | OFFLINE
```

## Reincorporación de nodos

Si un nodo que se encontraba `OFFLINE` vuelve a ejecutarse y comienza nuevamente a transmitir sus mensajes `RESOURCE_BEACON`, los demás nodos actualizan automáticamente su estado.

Ejemplo:

```text
[RECOVERY] nodo-02 volvió a estar ONLINE.
```

## Formato del RESOURCE_BEACON

Los mensajes intercambiados se serializan utilizando JSON.

La estructura general es:

```json
{
  "header": {
    "message_id": "UUID",
    "sender_id": "nodo-01",
    "type": "RESOURCE_BEACON",
    "timestamp": 1789010342069
  },
  "payload": {
    "ip_address": "127.0.0.1",
    "port": 9999,
    "cpu_free_pct": 90.0,
    "ram_free_mb": 2500.0,
    "active_tasks": 0
  }
}
```

Cada mensaje posee un identificador único mediante UUID v4 y una marca de tiempo Unix expresada en milisegundos.

## Parámetros del protocolo

| Parámetro                      | Valor      |
| ------------------------------ | ---------- |
| Protocolo de transporte        | UDP        |
| Formato de mensajes            | JSON       |
| Intervalo de `RESOURCE_BEACON` | 2 segundos |
| Timeout de un nodo             | 5 segundos |
| Estado inicial detectado       | `ONLINE`   |
| Estado después del timeout     | `OFFLINE`  |

## Resultados de la prueba

La prueba de concepto permitió verificar correctamente:

1. El descubrimiento bidireccional entre `nodo-01` y `nodo-02`.
2. La actualización de las tablas locales de vecinos.
3. El intercambio periódico de mensajes de presencia y recursos.
4. La detección de la caída de un nodo después del timeout definido.
5. La reincorporación automática de un nodo después de reiniciar su proceso.

Para la validación local se utilizaron dos procesos independientes ejecutados sobre el mismo computador mediante `localhost`, utilizando los puertos UDP `9999` y `10000`.
