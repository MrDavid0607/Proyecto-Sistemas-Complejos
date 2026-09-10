# ComplexNet API

Proyecto integrador de la asignatura **Sistemas Complejos**.

ComplexNet API propone una arquitectura para computación descentralizada sobre redes Ad hoc, en la cual diferentes nodos pueden descubrirse, intercambiar información y mantener una visión local de los participantes activos de la red.

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
