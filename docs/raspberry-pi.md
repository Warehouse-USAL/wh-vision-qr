# Raspberry Pi 3: instalación y pruebas

Guía para poner el módulo a leer QR en una Raspberry Pi 3 sin pantalla. Sirve
tanto para quien la prepara por primera vez como para el equipo de vehículos
cuando la integre.

> **Estado.** Todo lo de esta guía está verificado en laptop. Lo que depende
> del hardware (rendimiento real, cámara USB, alimentación) **hay que medirlo
> en la Pi**: para eso existen `benchmark.py` y `probar_camara.py`. Los números
> de la laptop no se pueden extrapolar sin medir.

## 1. Qué hace falta

| | Recomendado | Notas |
|---|---|---|
| Placa | Raspberry Pi 3 (B o B+) | 1 GB de RAM, 4 núcleos. La B solo tiene Wi-Fi de 2,4 GHz; la B+ también 5 GHz |
| Tarjeta | microSD de 16 GB o más | **8 GB alcanza**: la imagen Lite ocupa unos 2,9 GB. Pero deja poco margen para logs, clips y el buffer de eventos |
| Alimentación | 5 V / 2,5 A estables | Una fuente floja baja la frecuencia de la CPU y falsea cualquier medición de rendimiento |
| Cámara | USB (UVC) o módulo CSI | Ver la sección de cámaras. La GoPro Hero 5 **no** sirve como cámara en vivo |
| Red | Cable o hotspot del celular para la primera vez | El Wi-Fi de una universidad (WPA2-Enterprise) no se configura desde el Imager |

## 2. Preparar la tarjeta

Con **Raspberry Pi Imager** en la laptop:

1. Dispositivo: *Raspberry Pi 3*.
2. Sistema: *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (64-bit)**. Es la
   versión sin escritorio. Elegimos 64 bits porque OpenCV publica paquetes ya
   compilados para esa arquitectura y no hay que compilar nada; la Pi 3 lo
   soporta (la 32 bits también funciona, pero pasa por otros canales de paquetes).
3. Antes de escribir, abrir **Editar ajustes** y completar: nombre del equipo
   (por ejemplo `rover01`), usuario y contraseña, red Wi-Fi (o dejarla vacía si
   se usa cable) y **habilitar SSH**.
4. Escribir la tarjeta, ponerla en la Pi y encenderla. El primer arranque tarda
   un par de minutos porque expande la partición.

## 3. Entrar por SSH

Desde PowerShell en la laptop:

```
ssh USUARIO@rover01.local
```

Si `rover01.local` no resuelve, buscar la IP de la Pi en el router o probar con
`arp -a` y usar `ssh USUARIO@LA.IP`.

## 4. Instalar

Ya adentro de la Pi:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git libzbar0 python3-venv v4l-utils

git clone https://github.com/Warehouse-USAL/wh-vision-qr.git wh-vision-qr
cd wh-vision-qr

python3 -m venv .env
source .env/bin/activate
pip install -r requirements-pi.txt -r requirements-dev.txt
```

**Si el repositorio todavía no existe**, llevar el código desde la laptop en un
zip. En PowerShell, en la carpeta donde está el archivo:

```
scp vision-qr-prototipo.zip USUARIO@rover01.local:
```

y en la Pi:

```bash
sudo apt install -y unzip
unzip vision-qr-prototipo.zip        # crea la carpeta vision-qr/
cd vision-qr
```

seguido de las tres líneas del entorno virtual de arriba.

`requirements-pi.txt` usa `opencv-python-headless`, la variante sin interfaz
gráfica: en una Lite no hay pantalla y esa versión es bastante más liviana.

`libzbar0` es el motor de decodificación (una biblioteca del sistema, escrita
en C); `pyzbar` es solo el puente que lo llama desde Python. Se instalan por
separado.

Verificar que quedó bien:

```bash
python -c "import cv2; from pyzbar.pyzbar import decode; print('OK', cv2.__version__)"
python -m pytest
```

`pytest` viene de `requirements-dev.txt`; sin ese archivo el segundo comando
falla con `No module named pytest`. Los tests tardan más que en la laptop (los
de punta a punta ejecutan el programa completo varias veces): es normal.

## 5. Medir: ¿corre en esta Pi?

Este es el paso que contesta la duda de fondo, con un número.

```bash
python benchmark.py
```

Mide cuánto tarda el decodificador en un cuadro vacío (el caso más común) y en
uno con etiqueta, para varias resoluciones, y lo compara contra el objetivo de
10 fps del requisito RNF-01. También avisa si la placa se limitó por
temperatura o por alimentación durante la medición.

Cómo leerlo:

- **fps solo ZBar** es el techo del decodificador con la configuración de la Pi
  (respaldo apagado). Es lo que importa.
- **fps con respaldo** es lo mismo con el detector de OpenCV en cascada. El
  respaldo corre siempre que ZBar no encuentra nada, o sea, en casi todos los
  cuadros, y cuesta tanto como ZBar. Por eso `config.pi.json` lo trae apagado.
- El techo real es **menor**: el benchmark no incluye la captura de la cámara,
  el bus USB ni el resto del programa. Se mide entero en el paso 7.

Con una foto real de la cámara como fondo, la medición es más representativa:

```bash
python buscar_camaras.py --guardar        # deja camara_0.png
python benchmark.py --cuadro camara_0.png
```

Si no se llega al objetivo, en este orden: bajar la resolución (640×480 →
320×240), mantener el respaldo apagado, y recién después pensar en otra cosa.

## 6. La cámara

### USB (UVC)

Lo más simple: se enchufa y aparece como `/dev/video0`.

```bash
ls /dev/video*
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext     # qué códecs y resoluciones soporta
```

`config.pi.json` pide el códec **MJPG**. Una cámara USB sin comprimir a
640×480 y 30 fps mueve unos 18 MB/s por un bus USB 2.0 que la Pi 3 comparte con
la red; en MJPG la cámara comprime y el bus queda libre, a cambio de un poco de
CPU. Si la lista de formatos no incluye MJPG, sacar la línea `fourcc`.

Para ver qué negoció realmente la cámara, que puede ser menos de lo pedido:

```bash
python probar_camara.py --sin-ventana --fourcc MJPG
```

Imprime `Camara negocio: 640x480 a 30 fps, codec MJPG` y, al salir con Ctrl+C,
los fps reales de todo el ciclo.

### Módulo de cámara (CSI)

```bash
sudo apt install -y python3-picamera2
```

El entorno virtual tiene que crearse con `--system-site-packages` para ver ese
paquete, y en el config: `"captura": { "tipo": "picamera", "ancho": 640, "alto": 480 }`.

### GoPro Hero 5

**No sirve como cámara en vivo.** El modo webcam por USB llegó con la Hero 8; la
Hero 5 Black solo puede dar video por HDMI y hace falta una capturadora, y la
Hero 5 Session ni siquiera tiene salida HDMI.

**Sí sirve para grabar clips y procesarlos después**, que es un uso valioso: da
el mejor caso posible (1080p o más, buena óptica) contra el cual comparar. Ver
la sección siguiente.

## 7. Sin cámara: probar con clips

Un clip grabado se reproduce como si fuera la cámara. Sirve para medir el
programa completo en la Pi sin depender de la cámara, y para repetir la misma
prueba después de cada cambio.

```bash
python grabar_clip.py --sin-ventana --segundos 20 --salida clips/vuelta1.mp4
```

Y en un `config.json`:

```json
"captura": { "tipo": "video", "ruta": "clips/vuelta1.mp4", "velocidad": 0 }
```

`"velocidad": 0` procesa lo más rápido posible: mide el techo de todo el
programa, no lo que dura el clip.

Para no editar nada hay un config ya armado, `config.pi-clip.json`, que lee
`clips/vuelta_640.mp4`:

```bash
python -m vision_qr.main --config config.pi-clip.json --reporte reportes/pi_clip.json --etiqueta "Pi 3, clip 640x480"
```

Termina solo al acabarse el clip y muestra el resumen con los **fps promedio**,
que es el número que importa.

**Ojo con lo que se compara.** El clip se procesa a la velocidad que dé el
equipo, pero el confirmador mide la ausencia de una etiqueta en segundos
*reales* (`segundos_para_reemitir`). Si la Pi procesa más lento que el clip,
esos segundos equivalen a menos video que en la laptop, y una etiqueta que ZBar
pierde un instante puede contarse como nueva. Con clips, comparar **fps y
cobertura** entre equipos; el número de eventos solo es comparable con una
cámara en vivo.

### En vivo con la cámara de la laptop

Para ver el flujo completo mientras la Pi no tiene cámara. La laptop captura y
emite la imagen por la red; la Pi la lee con la fuente `red`. Las dos tienen que
estar en la misma red (por ejemplo, las dos por Ethernet al mismo router).

En la **laptop** (PowerShell, con el entorno activado):

```powershell
python transmitir_camara.py
```

Imprime una línea `URL para la Pi: http://<ip>:8080/video`. Abrir
`http://localhost:8080/` en el navegador muestra lo mismo que recibe la Pi. La
primera vez, el firewall de Windows pregunta: permitir en redes privadas.

En la **Pi**, poner esa URL en `config.pi-red.json` y correr:

```bash
sed -i 's#IP_DE_LA_LAPTOP#192.168.1.50#' config.pi-red.json   # la IP que imprimió la laptop
python -m vision_qr.main --config config.pi-red.json --reporte reportes/pi_red.json --etiqueta "Pi 3, camara de la laptop"
```

Sin clip ni cámara, en la laptop: `python transmitir_camara.py --video clips/vuelta_2.mp4`
repite un clip en bucle como si fuera la cámara. Se corta con Ctrl+C.

Limitaciones: es una demostración, no una medición. Los fps incluyen la
compresión JPEG y la red, y dependen de ellas; la cámara USB definitiva se
mide con `probar_camara.py` en la Pi. Si la laptop se apaga, la Pi reintenta
cada 2 segundos y sigue sola cuando vuelve. Si la red separa los equipos (pasa
en redes institucionales), la Pi no llega a la laptop: usar el cable directo o
el hotspot del celular.

### Clips de la GoPro

Grabar con la GoPro lo más angosto que permita su campo de visión (el gran
angular deforma los bordes), y pasar los archivos a la laptop con un lector de
microSD. Después, reprocesarlos **a distintas resoluciones** para saber cuánto
hace falta:

```json
"captura": { "tipo": "video", "ruta": "clips/gopro1.mp4", "velocidad": 0 }
"captura": { "tipo": "video", "ruta": "clips/gopro1.mp4", "velocidad": 0, "ancho": 1280 }
"captura": { "tipo": "video", "ruta": "clips/gopro1.mp4", "velocidad": 0, "ancho": 640 }
```

Con solo `ancho`, el alto se calcula conservando la proporción (estirar un clip
16:9 deformaría los cuadrados del QR). Correr las tres con
`--reporte reportes/gopro_1080.json` (y así) y comparar cuántas paradas se leen.

**Regla práctica:** el QR necesita unos 2,5 píxeles por módulo para que
ZBar lo lea, y el código actual tiene 21 módulos por lado: unos **52 píxeles de
lado en la imagen final**. Eso se midió sobre una imagen limpia; con ruido, luz
irregular y movimiento hace falta bastante más, así que conviene apuntar a
100 píxeles o más.

## 8. Correr el módulo

```bash
python -m vision_qr.main --config config.pi.json --reporte reportes/pi1.json --etiqueta "Pi 3, cámara USB, 640x480"
```

Ya está sin ventana (`config.pi.json`). Para ver qué enfoca la cámara sin
pantalla:

```bash
python buscar_camaras.py --guardar
```

y traer la foto a la laptop desde PowerShell:

```
scp USUARIO@rover01.local:wh-vision-qr/camara_0.png .
```

### Lo que ve el resto del sistema

- **Localmente**: `datos/estado.json` (`estado_local` en el config) se reescribe
  en cada parada con la última leída, la acción recomendada y el progreso de la
  misión. Es el canal para que el código de navegación reaccione sin red.
- **Por red**: los eventos, con buffer en disco si se corta la conexión. Ver
  [contrato-de-evento.md](contrato-de-evento.md).

## 9. Arranque automático (todavía sin probar en hardware)

Cuando ya ande de forma manual, se puede dejar como servicio. Este archivo es
un punto de partida **no validado en una Pi todavía**: verificar con
`systemctl status` la primera vez.

`/etc/systemd/system/vision-qr.service`:

```ini
[Unit]
Description=Escaner QR del Rover
After=network-online.target
Wants=network-online.target

[Service]
User=USUARIO
WorkingDirectory=/home/USUARIO/wh-vision-qr
ExecStart=/home/USUARIO/wh-vision-qr/.env/bin/python -m vision_qr.main --config config.pi.json
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vision-qr
journalctl -u vision-qr -f
```

## 10. Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| Pocos fps y `get_throttled` distinto de `0x0` | Fuente de alimentación floja o sobrecalentamiento. Medir con otra fuente |
| `get_throttled` da `0x50000` apenas arrancó | Muy habitual en la Pi 3: la tensión baja un instante al arrancar (`sudo dmesg \| grep -i voltage` muestra cuándo) y el aviso queda hasta reiniciar. Solo importa si los avisos aparecen **durante** la carga; `benchmark.py` distingue las dos situaciones |
| `Camara negocio` muestra menos resolución de la pedida | La cámara no soporta ese modo en ese códec. Ver `v4l2-ctl --list-formats-ext` |
| `No se pudo abrir la camara 0` | Otro proceso la tiene, o el usuario no está en el grupo `video` (`groups`) |
| Las marcas de tiempo de los eventos están corridas | La Pi no tiene reloj propio: sin red al arrancar, la hora puede estar mal hasta que sincronice. Revisar `timedatectl` |
| `pip install` falla con "externally-managed-environment" | Falta activar el entorno: `source .env/bin/activate` |
| `Unable to find zbar shared library` | Falta `sudo apt install libzbar0` |
