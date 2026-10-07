# Integración MQTT con la central

El equipo de Comunicación definió cómo se habla con la cámara: MQTT sobre
RabbitMQ, con un modelo **pedido-respuesta**. Este módulo lo implementa en
`vision_qr/nodo_mqtt.py` y mantiene todo lo propio (confirmación por cuadros,
política de paradas, estado local). Se activa con una sección `mqtt` en el
config; sin ella el módulo funciona como antes.

## Cómo funciona

```
Central ──set_target {qr, leg_id}──▶ devices/<id>/camera/cmd
Nodo    ──qr_detected────────────▶ devices/<id>/camera/event      (y borra el objetivo)
Nodo    ──llegada_parada (JSON completo)▶ devices/<id>/camera/stop_event   (política de paradas)
```

| Topic (`<id>` = `VEHICLE_ID`) | Sentido | QoS | Contenido |
|---|---|---|---|
| `devices/<id>/camera/cmd` | central → nodo | 1 | `set_target {qr, leg_id}`, `clear_target`, `telemetry_request` |
| `devices/<id>/camera/event` | nodo → central | 1 | `{"event":"qr_detected","qr","leg_id","timestamp"}` |
| `devices/<id>/camera/status` | nodo → central | 1 | `{"online": true/false}` (false es el último deseo) |
| `devices/<id>/camera/telemetry` | nodo → central | 0 | `camera_ok, fps, searching_qr, detections, cpu_temp, uptime_s` |
| `devices/broadcast/telemetry_request` | central → todos | | pide telemetría |
| `central/status` | central → nodo | | `offline` borra el objetivo |
| `devices/<id>/camera/stop_event` | nodo → central | 1 | **Propuesta nuestra**, ver abajo |

Los cuatro primeros y los de `central/` son **exactamente** los del código de
Comunicación (`rpi_camara.zip`), para que la central no note la diferencia.

### Qué cuenta como "coincide"

El objetivo `qr` coincide si es igual al **texto decodificado** (`WH2|PA1`) o al
**id de la parada** (`PA1`). Así la central puede pedir de cualquiera de las dos
formas mientras se define el nombre definitivo (el código de ellos usa
`Z1-L3-P07`, que no es nuestro formato).

El nodo confirma con `cuadros_para_confirmar_objetivo` cuadros consecutivos
(por defecto 1, igual que el de ellos). Subirlo a 2–3 evita avisos por una
lectura espuria, a costa de un poco de latencia.

### `stop_event` (propuesta)

El pedido-respuesta no incluye nuestra política de paradas (`accion`:
`detener` / `esperar_operador` / `continuar`). Mientras no se decida cómo llega
al Rover, cada parada confirmada se publica además, con el JSON completo del
[contrato de evento](contrato-de-evento.md), en `.../camera/stop_event`. Si
Comunicación prefiere otro topic o meter `accion` dentro de `qr_detected`, se
cambia en un solo lugar (`topic_parada`).

## Configuración

```json
"publicacion": { "tipo": "mqtt", "buffer": "datos/pendientes.jsonl" },
"mqtt": { "host": "192.168.0.10", "port": 1883, "vehicle_id": "VHC-001",
          "cuadros_para_confirmar_objetivo": 1 }
```

Variables de entorno (pisan al config; son las mismas del código de ellos):
`VEHICLE_ID`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`.
**Las credenciales no van en el repo**: usar `MQTT_USER` / `MQTT_PASS`.

Ejemplos: `config.laptop-mqtt.json` (webcam 640x480, broker local) y
`config.pi-mqtt.json` (320x240 MJPG, broker de la central).

## Resolución

El código de Comunicación pide 640x480 por defecto (`FRAME_WIDTH`/`FRAME_HEIGHT`)
y no fija MJPG. Con la cámara USB de la Pi 3 eso da ~9 fps con ZBar (medido),
por debajo de RNF-01. **Usamos 320x240 MJPG** (≈29,5 fps); el nodo MQTT corre
dentro de este módulo, así que la resolución se define en `captura` y no en
las variables de ellos.

## Probar sin la central ni la cámara real

Tres terminales en la laptop (Windows PowerShell), con `pip install -r requirements.txt amqtt`:

```
# 1. broker local
python broker_prueba.py

# 2. el módulo con la webcam de la notebook
python -m vision_qr.main --config config.laptop-mqtt.json

# 3. la central simulada pide QR y mide cuánto tarda
python central_simulada.py --qr PA1 WH2|PM2
```

Mostrarle a la webcam cada QR pedido (`python generar_etiquetas.py` los
genera; se pueden ver en pantalla del celular). La salida de (3) indica cuánto
tardó cada uno. `--solo-escuchar` muestra todo lo que publica el nodo.

Para probar con la **Pi y la cámara USB** más adelante: el broker corre en la
laptop (`python broker_prueba.py`), y en la Pi
`MQTT_HOST=<ip de la laptop> python -m vision_qr.main --config config.pi-mqtt.json --sin-ventana`.

## Comportamiento ante fallas

- Sin conexión al broker, el nodo **no avisa** `qr_detected` (no lo pierde: el
  objetivo queda pendiente) y el evento de parada completo va al buffer
  `datos/pendientes.jsonl`. Se reconecta solo.
- `central/status = offline` borra el objetivo: el Rover no queda esperando una
  lectura que nadie va a atender.
- Riesgo conocido del esquema de ellos: con QoS 1 y sesión persistente, un
  `qr_detected` viejo podría entregarse tarde tras una reconexión. Por eso lleva
  `timestamp` y `leg_id`; la central debería descartar los que no correspondan
  al tramo actual.

## Pendiente de acordar con Comunicación

Ver la lista de preguntas en el chat de la sesión; resumen: nombre definitivo
del QR (`WH2|PA1` vs `Z1-L3-P07`), topic de `stop_event`, credenciales y TLS,
fuente de hora (NTP) en la Pi, y quién retoma el recorrido tras
`esperar_operador`.
