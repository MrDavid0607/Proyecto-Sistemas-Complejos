# Guion del video — Fase 2 (6 a 8 minutos)

**Cómo usar este guion:** ponlo a un lado de la pantalla y graba solo la ventana de VS Code.
En cada escena hay dos bloques:

- **COPIAR:** el comando que pegas en la terminal de VS Code (`` Ctrl+` ``).
- **DECIR:** lo que dices mientras se ejecuta y al leer el resultado. Está escrito para leerlo
  casi tal cual; cambia las palabras que quieras.

Los tiempos son aproximados. Todo lo que dice "(si sale X)" depende de lo que veas en pantalla.

---

## Antes de grabar (no se graba esto)

1. Abre **Docker Desktop** y espera a que diga "Engine running".
2. En VS Code abre la carpeta `repo-github`. Cierra el panel de chat de la derecha para tener más espacio.
3. Abre una terminal (`` Ctrl+` ``) y deja el texto grande con `Ctrl+=` (2 o 3 veces).
4. Deja todo limpio y haz un ensayo completo (o al menos la escena 2) para que las imágenes de
   Docker queden en caché y el arranque sea rápido:

```powershell
docker compose down; Remove-Item logs -Recurse -Force -ErrorAction SilentlyContinue; cls
```

5. En el explorador de VS Code deja visibles las carpetas `src`, `tests`, `docs` y `scripts`.
6. Empieza a grabar. Cuando necesites limpiar la pantalla entre escenas, escribe `cls`.

---

## Escena 1 — Introducción (0:00 – 0:50)

**En pantalla:** el explorador de VS Code con el proyecto. Sin comandos.

**DECIR:**

> Hola, soy David. Les voy a mostrar la segunda entrega de ComplexNet API, el proyecto
> integrador de Sistemas Complejos.
>
> La idea del proyecto es ejecutar trabajo de inteligencia artificial sobre una red de nodos
> que se coordinan solos, sin un servidor central. Así evitamos tres problemas de las
> arquitecturas centralizadas: un único punto de falla, un cuello de botella, y la falta de
> adaptación cuando la red cambia.
>
> En la primera entrega hicimos el diseño y una prueba de concepto con dos nodos. En esta
> segunda entrega implementamos el núcleo funcional completo y lo corremos sobre una red de
> tres nodos en Docker. Voy a mostrar: el descubrimiento automático de nodos, la asignación
> de tareas, la detección de un nodo caído con reasignación de su tarea, y las pruebas.

---

## Escena 2 — La arquitectura en el código (0:50 – 1:40)

**En pantalla:** abre la carpeta `src` → `complexnet` en el explorador (haz clic en la flecha).

**COPIAR:**

```powershell
Get-ChildItem src\complexnet -Directory | Select-Object Name
```

**DECIR:**

> Este es el código. Cada servicio del diseño es un módulo independiente.
>
> `discovery` descubre nodos y mantiene la tabla de vecinos. `resources` mide la CPU y la memoria
> de cada nodo. `communication` es la capa de mensajes: usa UDP y JSON, pero detrás de una interfaz
> abstracta, así que se podría cambiar el transporte sin tocar el resto. `scheduler` es el
> planificador distribuido. `tasks` gestiona el ciclo de vida de las tareas y la reasignación.
> `failure_detection` detecta nodos caídos, `synchronization` tiene el reloj lógico de Lamport,
> y `monitoring` guarda los eventos y las métricas.
>
> Todo esto lo ejecuta cada nodo por su cuenta. Ningún nodo es especial.

---

## Escena 3 — Levantar la red de 3 nodos (1:40 – 2:50)

**COPIAR:**

```powershell
docker compose up --build -d
```

**DECIR (mientras arranca):**

> Cada nodo es un contenedor de Docker, y los tres comparten una red propia. Con un solo
> comando construyo la imagen y levanto los tres nodos.

**COPIAR:**

```powershell
docker compose ps
```

**DECIR:**

> Aquí están los tres: nodo-01, nodo-02 y nodo-03, con sus direcciones en la red.

**COPIAR:**

```powershell
docker logs complexnet-nodo-01 2>&1 | Select-String "NODE_STARTED|DISCOVERY"
```

**DECIR:**

> Este es el log del nodo-01. Arrancó sin conocer a nadie, porque aquí `seeds` vale cero.
> Cada nodo anuncia su presencia por UDP broadcast cada dos segundos, y en pocos segundos
> el nodo-01 descubrió a los otros dos por sí solo. Nadie le dijo dónde estaban.

**COPIAR:**

```powershell
Invoke-RestMethod http://localhost:8001/status | Select-Object -ExpandProperty peers | Select-Object node_id,ip,status,latency_ms,bandwidth_mbps,reputation | Format-Table
```

**DECIR:**

> Esta es la tabla de vecinos del nodo-01, la PeerTable. Cada nodo tiene la suya, no hay una
> tabla global. Para cada vecino guarda el estado, que ahora es ONLINE, la latencia que mide
> con mensajes ping y pong, que está por debajo de un milisegundo, el ancho de banda anunciado
> y la reputación, que empieza en 1.

---

## Escena 4 — Asignación de tareas de IA (2:50 – 4:00)

**COPIAR:**

```powershell
.\.venv\Scripts\python.exe scripts/demo.py normal
```

**DECIR (mientras corre y al ver el resultado):**

> Ahora envío cinco tareas de inteligencia artificial al nodo-01. Cada tarea es una regresión
> lineal que se ejecuta en otro nodo de la red.
>
> Cada línea muestra la tarea, el nodo que la ejecutó, los intentos, y el modelo que se
> obtuvo. La pendiente da aproximadamente 2.35 y el intercepto 0.81, que son los valores
> reales con los que generamos los datos, y el R cuadrado es 0.99. O sea que el modelo se
> entrenó bien en un nodo remoto y el resultado volvió al nodo que lo pidió.

**COPIAR:**

```powershell
docker logs complexnet-nodo-01 2>&1 | Select-String "TASK_ASSIGNED" | Select-Object -Last 3
```

**DECIR:**

> Así decidió el planificador. El nodo-01 calcula una puntuación para cada candidato con la
> función de aptitud que diseñamos en la primera entrega. La CPU libre y la memoria pesan el
> ochenta por ciento, y el resto se reparte entre ancho de banda, reputación y latencia.
> Gana el nodo con mayor puntuación. Aquí se ve el nodo elegido y su score.
>
> Una observación: como todos los nodos están desocupados, sus diferencias de CPU son muy
> pequeñas, pero la normalización las amplifica. Por eso el nodo ganador puede cambiar de una
> ejecución a otra. Es una consecuencia del modelo, que no considera la carga actual.

---

## Escena 5 — Incremento de carga (4:00 – 4:40)

**COPIAR:**

```powershell
.\.venv\Scripts\python.exe scripts/demo.py carga
```

**DECIR:**

> Probamos ahora subiendo la carga: dos tareas, luego seis y luego doce. Todas se completan,
> y vemos el tiempo total de cada lote y los nodos que las ejecutaron. Esto es parte de las
> métricas de escalabilidad que vamos a profundizar en la tercera entrega.

---

## Escena 6 — Un nodo cae durante una tarea (4:40 – 6:20)

Esta es la escena más importante. Tarda cerca de 30 segundos; habla mientras espera.

**COPIAR:**

```powershell
.\.venv\Scripts\python.exe scripts/demo.py fallo
```

**DECIR (al aparecer "la tarea fue asignada a nodo-XX; se detiene su contenedor"):**

> Ahora la prueba de tolerancia a fallos. Envío una tarea larga, de unos veinte segundos, y
> el script la asigna a un nodo. Justo ahora le apago el contenedor a ese nodo, como si se
> hubiera caído o salido de la red.
>
> *(mientras espera)* El nodo que pidió la tarea deja de recibir mensajes de ese vecino. El
> requisito era detectar la caída en un máximo de cinco segundos. Cuando se cumple, marca el
> nodo como OFFLINE y reasigna la tarea a otro nodo que siga vivo.
>
> *(al terminar)* La tarea terminó, y fíjense: intentos igual a 2 y reasignaciones igual a 1.
> Se completó en otro nodo, y el resultado es correcto. La red se adaptó al fallo sin que
> nadie interviniera y sin ningún coordinador central.

**COPIAR:**

```powershell
docker logs complexnet-nodo-01 2>&1 | Select-String "FAILURE|TASK_REASSIGN|TASK_COMPLETED|RECOVERY" | Select-Object -Last 6
```

**DECIR:**

> Este es el registro de eventos, en orden. Primero `FAILURE`: el nodo se declara OFFLINE
> después de cinco segundos de silencio. Luego `TASK_REASSIGN`: la tarea sale del nodo caído.
> Después se asigna al nuevo nodo y aparece `TASK_COMPLETED` con dos intentos. Al final, el
> script reinició el contenedor y el log marca `RECOVERY`: el nodo volvió a la red.

---

## Escena 7 — Salida y entrada de un nodo (6:20 – 6:55)

**COPIAR:**

```powershell
.\.venv\Scripts\python.exe scripts/demo.py ingreso
```

**DECIR:**

> Último escenario de red: apago el nodo-03 y miro cómo lo ve el nodo-01. Su estado cambia a
> OFFLINE. Lo vuelvo a encender y cambia otra vez a ONLINE. El nodo se reincorpora solo, solo
> porque vuelve a emitir sus mensajes de presencia.

---

## Escena 8 — Registro de eventos y reloj de Lamport (6:55 – 7:25)

**COPIAR:**

```powershell
Get-Content logs\nodo-01.jsonl -Tail 4
```

**DECIR:**

> Cada nodo guarda un registro de eventos en formato JSON. Cada línea tiene la hora, el nodo,
> el evento y un campo llamado `lamport`. Ese es un reloj lógico: se incrementa con cada
> mensaje y se ajusta con los mensajes que llegan de otros nodos. Sirve para ordenar los
> eventos de los tres nodos sin depender de que sus relojes estén sincronizados. Es el
> mecanismo de sincronización de esta entrega.

---

## Escena 9 — Pruebas automáticas (7:25 – 8:00)

**COPIAR:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```

**DECIR (mientras corre, unos 25 segundos):**

> Por último, las pruebas. Hay cuarenta y dos entre unitarias y de integración. Las unitarias
> verifican el planificador, incluyendo el ejemplo numérico del diseño, los mensajes, el reloj
> de Lamport y el detector de fallos, que respeta exactamente el límite de cinco segundos.
> Las de integración levantan tres nodos reales, envían una tarea de IA, tumban al nodo que
> la ejecuta y verifican que se reasigne y termine.
>
> *(al terminar)* Las cuarenta y dos pasan.

---

## Escena 10 — Cierre (8:00 – 8:30)

**COPIAR:**

```powershell
docker compose down
```

**DECIR:**

> Con esto cumplimos los entregables de la segunda fase: descubrimiento automático, registro
> de recursos, mensajería, asignación y reasignación de tareas, detección de fallos, registro
> de eventos y pruebas, sobre una red de tres nodos.
>
> Para la tercera entrega queda construir la API de alto nivel, las tres aplicaciones, incluida
> la de inteligencia artificial, un panel de monitoreo y los experimentos de latencia y
> escalabilidad. Gracias.

---

## Si algo sale mal mientras grabas

| Problema | Qué hacer |
|---|---|
| `demo.py` dice "La red no se formó a tiempo" | Espera 10 s y repite. Si sigue, `docker compose ps` para ver si los 3 contenedores están `Up` |
| Un `Select-String` no muestra nada | Los nodos acaban de arrancar o ya pasaron muchos eventos; corre antes el escenario correspondiente |
| El nodo ganador es distinto al del guion | Es normal; di el nombre del que aparezca |
| Docker no responde | Reinicia Docker Desktop y empieza de nuevo desde "Antes de grabar" |
| Quieres repetir una escena | Pausa la grabación y corta después; las escenas no dependen entre sí, salvo que la red (escena 3) debe estar arriba |

## Referencia rápida de comandos (en orden)

```powershell
docker compose up --build -d
docker compose ps
docker logs complexnet-nodo-01 2>&1 | Select-String "NODE_STARTED|DISCOVERY"
Invoke-RestMethod http://localhost:8001/status | Select-Object -ExpandProperty peers | Select-Object node_id,ip,status,latency_ms,bandwidth_mbps,reputation | Format-Table
.\.venv\Scripts\python.exe scripts/demo.py normal
docker logs complexnet-nodo-01 2>&1 | Select-String "TASK_ASSIGNED" | Select-Object -Last 3
.\.venv\Scripts\python.exe scripts/demo.py carga
.\.venv\Scripts\python.exe scripts/demo.py fallo
docker logs complexnet-nodo-01 2>&1 | Select-String "FAILURE|TASK_REASSIGN|TASK_COMPLETED|RECOVERY" | Select-Object -Last 6
.\.venv\Scripts\python.exe scripts/demo.py ingreso
Get-Content logs\nodo-01.jsonl -Tail 4
.\.venv\Scripts\python.exe -m pytest tests -v
docker compose down
```
