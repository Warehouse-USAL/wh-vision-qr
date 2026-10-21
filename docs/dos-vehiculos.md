# Una Pi fija, dos vehículos (cámaras por red)

Plan para cuando hay **una sola Raspberry Pi**: la Pi queda fija (con corriente de
red, idealmente por cable) y lee el video de **dos cámaras por red**, por ejemplo dos
celulares con una app de cámara IP. Corre un nodo completo por vehículo; para la
central son dos cámaras independientes (`camera_VHC-xxx`).

No cambia el programa de siempre: `dos_vehiculos.py` arma dos configs a partir de
`config.pi-red-mqtt.json` y lanza `python -m vision_qr.main` dos veces.

## Qué hace falta saber antes

| Dato | De dónde sale |
| --- | --- |
| Id MQTT del vehículo 1 y del vehículo 2 (ej. `VHC-005` y otro) | Comunicación |
| IP y puerto del broker, usuario y clave | Comunicación |
| URL del video de cada celular (ej. `http://IP_DEL_CELULAR:8080/video`) | La app de cámara IP la muestra al iniciar |

El usuario y la clave **no se guardan en ningún archivo** (el repo es público): van por
las variables `MQTT_USER` y `MQTT_PASS`.

## Preparar (una vez, con internet)

```
cd ~/vision-qr && source .env/bin/activate
git pull
```

## Probar en casa, sin la facultad

Broker local en la laptop y los dos "celulares" simulados con la webcam:

```
# Laptop, terminal 1
py broker_prueba.py
# Laptop, terminal 2 y 3 (una cámara cada una; la segunda puede repetir la webcam)
py transmitir_camara.py
py transmitir_camara.py --puerto 8081
```

En la Pi:

```
python dos_vehiculos.py --broker IP_LAPTOP --v1 VHC-005 --cam1 http://IP_LAPTOP:8080/video \
                        --v2 VHC-006 --cam2 http://IP_LAPTOP:8081/video
```

(`--cam1` y `--cam2` tienen que ser URL distintas; con la misma, el script avisa.)

Pedir un QR a cada uno desde la laptop (**con `--sin-estado`** cuando hay más de una central):

```
py central_simulada.py --vehiculo VHC-005 --qr PA1 --sin-estado
py central_simulada.py --vehiculo VHC-006 --qr PM2 --sin-estado
```

## En la facultad

```
MQTT_USER=... MQTT_PASS=... python dos_vehiculos.py --broker 192.168.0.13 \
    --v1 VHC-005 --cam1 http://IP_CELULAR_1:8080/video \
    --v2 VHC-0xx --cam2 http://IP_CELULAR_2:8080/video
```

- Cada línea de la salida lleva el prefijo `[VHC-005]` o `[VHC-0xx]`.
- Esperado: `++ MQTT conectado ... como VHC-005` y lo mismo para el otro.
- Con `--solo-generar` solo escribe las configs (en `datos/dos_vehiculos/`) y muestra qué haría.
- Ctrl+C (o `kill`) corta los dos nodos y cada uno imprime su resumen.

## Cosas a tener en cuenta

- **No correr `central_simulada.py` sin `--sin-estado` si la central real está encendida**:
  al terminar publica `central/status offline` y los nodos descartan su objetivo.
- **Resolución de los celulares:** 320×240 o 640×480. Con 720p o más, dos videos saturan el
  Wi-Fi de 2,4 GHz de la Pi 3. Mejor la Pi por cable.
- **Latencia:** el video por Wi-Fi llega con retraso. Medirlo: poner un cronómetro en la
  laptop, apuntarle el celular y comparar con lo que muestra la vista web de la Pi.
  El error de frenado es `velocidad × latencia total`.
- **Foco:** muchos celulares no enfocan a menos de ~10 cm. Probar con el QR a la distancia real.
- **CPU:** dos nodos a 320×240 deberían usar ~1,3–1,6 de los 4 núcleos de la Pi 3
  (estimación, sin medir en la Pi). Verlo con `top` mientras corren.
- Cada vehículo tiene su `estado-<id>.json` y su `pendientes-<id>.jsonl` en `datos/dos_vehiculos/`.
