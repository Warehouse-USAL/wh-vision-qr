# Manejar la Raspberry Pi desde otra PC

Guía para quien no armó el sistema y necesita levantar el nodo QR en la Pi
desde su propia computadora. **No hace falta instalar nada en la PC**: el
código ya está en la Pi y se maneja por SSH.

## Qué hace falta

| Dato | De dónde sale |
| --- | --- |
| PC en la **misma red Wi-Fi** que la Pi (facultad: `Emergentes-2.4`) | — |
| IP de la Pi (última conocida: `192.168.0.241`) o el nombre `rover-01.local` | quien armó la Pi |
| Usuario `rover` y su contraseña | quien armó la Pi (no está en el repo) |
| IP del broker (última conocida: `192.168.0.11`), usuario y clave | Comunicación |
| Id del vehículo (ej. `VHC-000`) | Comunicación |

El usuario y la clave del broker nunca se guardan en archivos del repo
(es público).

## Levantar el nodo

En PowerShell (Windows) o en una terminal:

```
ssh rover@192.168.0.241
```

Ya dentro de la Pi:

```
cd ~/vision-qr
git pull
./iniciar_pi.sh VHC-000 192.168.0.11 P1
```

Los tres datos son vehículo, broker y home (`P1` o `P2`). Sin argumentos usa
`VHC-000`, `192.168.0.11` y `P1`. El script pide el usuario y la clave del
broker (o las toma de `MQTT_USER` y `MQTT_PASS`).

Antes de arrancar chequea que llegue al broker y que la Pi vea la cámara; si
algo falla lo dice en vez de dejar un error largo.

Tiene que aparecer:

```
++ MQTT conectado a 192.168.0.11:1883 como VHC-000
```

y queda esperando los pedidos de la central (`>> buscando QR 'WH2|PA1'`).

- **Vista en vivo** de lo que ve la cámara: `http://IP_DE_LA_PI:8080/` (el
  script imprime la dirección).
- **Cortar:** `Ctrl+C`.
- **Apagar la Pi:** `sudo shutdown -h now`, esperar a que se apague el LED
  verde y recién ahí sacar la corriente.

## Con la webcam de una laptop en vez de la cámara de la Pi

En la laptop, dentro de la carpeta del proyecto:

```
py transmitir_camara.py --ancho 320 --alto 240
```

y en la Pi, con la IP que muestra la laptop:

```
CAMARA_URL=http://IP_LAPTOP:8080/video ./iniciar_pi.sh VHC-000 192.168.0.11 P1
```

## Si algo falla

| Síntoma | Causa probable |
| --- | --- |
| `ssh` da timeout | La PC no está en la misma red, la Pi está apagada o cambió de IP (mirar la lista de dispositivos del router o probar `rover-01.local`). |
| `No llego al broker` | IP del broker incorrecta o el servidor caído: confirmarlo con Comunicación. |
| `La Pi no detecta la camara CSI` | Cinta mal puesta. Con la Pi **apagada**: contactos metálicos hacia el HDMI en la Pi, hacia la placa en la cámara. Encender y probar `rpicam-hello --list-cameras`. |
| Conecta pero no aparece `>> buscando QR` | El id del vehículo no coincide con el que usa la central. |
| `>> objetivo descartado` enseguida | La central canceló el pedido por tiempo antes de que se mostrara el QR. |
| El QR no se lee | Ver la vista en vivo: la cámara V2 es de foco fijo y de cerca se ve borrosa. |

Más detalles: `docs/raspberry-pi.md`, `docs/mqtt.md` y `docs/dos-vehiculos.md`.
