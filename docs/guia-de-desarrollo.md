# Guía de desarrollo

Guía larga para trabajar con el módulo en una laptop: elegir entorno,
instalar, probar la cámara, medir. El resumen del proyecto está en el
[README](../README.md); para la Raspberry Pi, ver
[raspberry-pi.md](raspberry-pi.md).

Los comandos asumen que se ejecutan desde la raíz del repositorio.

---

## 0. ¿Windows, WSL2 o máquina virtual?

Respuesta corta: **el destino final es Linux sobre la Raspberry Pi, pero eso
no obliga a desarrollar en Linux.** La única diferencia real entre sistemas
en este proyecto está en la capa de captura, que ya está abstraída.

### Lo que conviene

| Entorno | Sirve para | Cámara en vivo |
|---|---|---|
| **WSL2 (Ubuntu)** | Todo el desarrollo. Mismo `apt`, mismos paquetes que la Pi | **No** (salvo trabajo extra) |
| **Windows nativo** | Grabar clips y probar con la webcam | Sí |
| **Máquina virtual** | Solo si necesitás cámara en vivo dentro de Linux | Con fricción |
| **Raspberry Pi** | La única validación que cuenta | Sí |

**La recomendación: WSL2 para el código, Windows para grabar, Pi para validar.**

Grabás un clip una vez en Windows, lo reproducís infinitas veces en WSL2. Es
más rápido que cualquier VM, es Ubuntu real, y además vuelve tus pruebas
reproducibles, que es algo que la cámara en vivo nunca te va a dar.

### WSL2 (lo más recomendable)

```powershell
wsl --install -d Ubuntu
```

Reiniciás, y adentro de Ubuntu:

```bash
sudo apt update
sudo apt install -y libzbar0 python3-venv python3-pip
python3 -m venv .env && source .env/bin/activate
pip install -r requirements.txt
```

Es exactamente lo mismo que vas a correr en la Pi, incluido `libzbar0`. En
Windows 11 las ventanas gráficas funcionan solas por WSLg, así que
`cv2.imshow` anda. En Windows 10 viejo, usá `--sin-ventana`.

Tus archivos de Windows están en `/mnt/c/`, así que podés editar con VS Code
en Windows y correr en Linux sin copiar nada.

**Lo único que WSL2 no te da es la webcam.** El kernel por defecto no trae
los drivers de video USB, y habilitarlos implica compilar un kernel propio.
No vale la pena: para eso está el flujo de grabar y reproducir.

### Máquina virtual (VirtualBox o VMware)

Andá por acá solo si realmente necesitás cámara en vivo dentro de Linux.

- **VMware Workstation Player**: el pasaje de cámara es el más confiable.
- **VirtualBox**: necesitás el Extension Pack, y después
  `VBoxManage controlvm "Ubuntu" webcam attach .0`
- **Hyper-V**: no sirve, no tiene pasaje de USB para cámaras. Evitalo.

Dos advertencias. La cámara dentro de una VM suele perder cuadros y agregar
latencia, así que vas a estar depurando problemas del hipervisor en lugar de
tu código. Y cualquier medición de rendimiento que hagas ahí **no significa
nada**: el número que importa es el de la Raspberry Pi.

### Lo que no hace falta

Instalar Ubuntu en arranque dual solo para este proyecto. El costo no se
justifica: la Pi es tu entorno Linux real, y la tenés disponible.

---

## 1. El flujo grabar y reproducir

Este es el patrón que hace que la elección de sistema operativo deje de
importar.

**En Windows**, grabás un clip:

```powershell
python grabar_clip.py --segundos 20 --salida clips/pasillo_A.mp4
```

**En WSL2, en la Pi o donde sea**, lo reproducís:

```json
"captura": { "tipo": "video", "ruta": "clips/pasillo_A.mp4" }
```

Opciones útiles:

```json
"velocidad": 0      // lo más rápido posible: mide el techo del pipeline
"repetir": true     // en bucle
"saltar": 2         // procesa 1 de cada 3 cuadros (simula una Pi lenta)
```

Por qué importa más de lo que parece:

- **Tus pruebas se vuelven reproducibles.** Cambiás el decodificador y volvés
  a correr el mismo clip: si baja la tasa de acierto, fue tu cambio. Con
  cámara en vivo nunca sabés si fue el código o la luz.
- **Es la única forma honesta de medir el barrido por movimiento.** Grabás el
  Rover avanzando y medís cuántas etiquetas sobreviven de verdad.
- **Documenta fallas.** Cuando una etiqueta no se lea en el warehouse, el
  clip vale más que cualquier descripción escrita.

---

## 2. Instalación en Windows

Abrí **PowerShell** en la carpeta del proyecto (Shift + clic derecho → "Abrir
ventana de PowerShell aquí").

```powershell
py -m venv .env
.env\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Si `Activate.ps1` da error de "ejecución de scripts deshabilitada":**

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.env\Scripts\Activate.ps1
```

Eso solo afecta a esa ventana, no cambia nada del sistema. Alternativa: usá
`cmd` en lugar de PowerShell y activá con `.env\Scripts\activate.bat`.

Sabés que está activado porque el prompt arranca con `(.env)`.

### Si pyzbar falla al importar

`pyzbar` trae las DLL de ZBar incluidas en Windows, pero necesitan el
**Visual C++ Redistributable 2013 (x64)**. Si al correr aparece
`FileNotFoundError: Could not find module "libzbar-64.dll"`, instalá
[vcredist_x64 2013](https://www.microsoft.com/download/details.aspx?id=40784)
y reiniciá la terminal.

Verificá que quedó bien:

```powershell
python -c "from pyzbar.pyzbar import decode; import cv2; print('todo OK', cv2.__version__)"
```

---

## 3. Encontrar tu cámara

En Windows el índice 0 **no siempre es tu webcam**. Cámaras virtuales de
Teams, OBS o Nvidia Broadcast suelen ocupar los primeros lugares.

```powershell
python buscar_camaras.py --guardar
```

Te lista los índices disponibles y guarda una imagen de cada uno. Abrí los
`camara_N.png`, mirá cuál es la real y usá ese número en `config.json`.

**Si no encuentra ninguna:** Configuración → Privacidad y seguridad → Cámara,
y activá **"Permitir que las aplicaciones de escritorio accedan a la cámara"**.
Ese permiso está apagado por defecto en muchas instalaciones y es la causa
más común del problema. Cerrá también Teams, Zoom u OBS si están abiertos.

---

## 4. Primera prueba: ¿la cámara lee QR?

Antes que nada, esto:

```
python probar_camara.py
```

Mostrale **cualquier** código QR: el de un envase, uno generado en una web,
el QR del wifi, una factura. No hace falta generar nada todavía.

- **Contorno verde** = es una etiqueta del proyecto
- **Contorno amarillo** = es un QR cualquiera, se lee bien pero no es nuestro

Si ves contornos y contenido en consola, la cámara y el decodificador
funcionan. Eso es todo lo que hay que validar en esta etapa.

### Por qué existe este script aparte de `main.py`

`main.py` **descarta en silencio** cualquier QR que no empiece con el prefijo
del proyecto. Eso es a propósito (requisito RF-04): el Rover no debe reportar
el código de barras de un envase de Coca-Cola que quedó en una estantería.

Pero al probar por primera vez, ese filtro hace parecer que nada funciona.
Por eso `probar_camara.py` no filtra nada y muestra todo lo que ve.

**El orden correcto es:**

1. `probar_camara.py` → ¿la cámara lee QR? (esta sección)
2. `generar_etiquetas.py` → recién cuando el paso 1 anda
3. `main.py` → el módulo real, con filtro y publicación

---

## 5. El recorrido y las etiquetas

El circuito tiene **seis paradas fijas** en forma de U:

```
PA1 → PA2 → PA3 → PM1 → PM2 → PM3 → (vuelve a PA1)

PA1, PA2, PA3   automáticas — el Rover se detiene solo al leerlas
PM1, PM2, PM3   manuales    — requieren intervención de un operador
```

Cada parada tiene un QR pegado que dice qué parada es. Nada más:

```
WH2|PA1
 |   `-- identificador de parada
 `------ prefijo + versión del esquema
```

Generalas con:

```
python generar_etiquetas.py                  # las seis, 10 cm
python generar_etiquetas.py --hoja-prueba    # una A4 con las seis, para probar sin imprimir
python generar_etiquetas.py --paradas PM2    # reimprimir una sola
```

### Política de paradas

No siempre el Rover tiene que detenerse en las seis. Dos parámetros de
`config.json` lo controlan:

```json
"paradas_activas": ["PA1", "PM2"],
"minimo_paradas": 0
```

- `paradas_activas`: dónde puede detenerse. `null` = las seis.
- `minimo_paradas`: cuántas de esas hacen falta. `0` = todas las activas.

| Configuración | Significa |
|---|---|
| `null` y `0` | las seis (comportamiento base) |
| `["PA1","PM2"]` y `0` | esas dos, y solo esas |
| `null` y `4` | cuatro cualesquiera de las seis |
| `["PA1","PA2","PA3","PM1"]` y `3` | tres cualesquiera de esas cuatro |

Cada evento lleva una `accion` recomendada: `detener` (activa y automática),
`esperar_operador` (activa y manual) o `continuar` (inactiva). **El módulo no
frena al Rover**: recomienda, y quien controla los motores decide si puede
cumplirlo. Una parada inactiva se lee y se reporta igual; lo que cambia es la
acción y que no cuenta para el mínimo.

Una configuración imposible (una parada que no existe, un mínimo mayor que las
paradas activas) se rechaza al arrancar con un mensaje claro.

### Seguimiento del recorrido

Como el orden es conocido, el módulo avisa cuando una parada llega fuera
de secuencia:

```
-> PA1  [AUTO]  parada 1 de 6
-> PA3  [AUTO]  parada 3 de 6   (!) sin leer: PA2
```

Eso detecta tres cosas que de otro modo pasan inadvertidas: una etiqueta
pegada en el lugar equivocado, una parada que el Rover pasó de largo, y
una lectura espuria.

**El aviso no rechaza la lectura**, solo la marca. Un salto puede ser
legítimo — el Rover se reinició a mitad de recorrido, alguien lo movió a
mano, está haciendo una vuelta parcial de prueba — y descartar una lectura
correcta es peor que registrarla con una advertencia. Qué hacer con el
aviso lo deciden Backend y navegación, no la capa de visión.

---

## 6. Notas de Windows que importan

**Backend de cámara.** El código usa DirectShow automáticamente en Windows.
El backend por defecto de OpenCV (Media Foundation) tarda varios segundos en
abrir la cámara e ignora los pedidos de resolución. Si querés forzar otro,
agregá `"backend": "msmf"` al bloque de captura.

**Dos terminales.** Para probar con el servidor simulado necesitás dos
ventanas de PowerShell, cada una con su `.env\Scripts\Activate.ps1`.

**Firewall.** La primera vez que corras `servidor_prueba.py`, Windows va a
preguntar si permitís la conexión. Alcanza con redes privadas.

**Esto es solo para desarrollar.** El despliegue final es sobre Raspberry Pi
con Linux. Windows es tu entorno de laboratorio, no el de producción: no
inviertas tiempo en resolver problemas específicos de Windows que no vas a
tener en la Pi.

---

## 7. Instalación en Linux y macOS

### Linux (y Raspberry Pi)

```bash
sudo apt update
sudo apt install -y libzbar0 python3-venv
python3 -m venv .env && source .env/bin/activate
pip install -r requirements.txt
```

### macOS

```bash
brew install zbar
python3 -m venv .env && source .env/bin/activate
pip install -r requirements.txt
```

> Si aparece `Unable to find zbar shared library`, exportá antes de correr:
> `export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH`

---

## 8. Verificar que la elección técnica es correcta

```bash
python ensayo_robustez.py
```

Degrada una etiqueta de catorce formas distintas y compara ZBar contra el
detector nativo de OpenCV. Resultado esperado: ZBar resuelve rotación de 45°,
perspectiva fuerte y códigos lejanos donde OpenCV falla.

**El único modo de falla serio es el barrido por movimiento.** No se corrige
por software: se corrige con iluminación y obturación en el montaje físico.

---

## 9. Probar la integración con el Backend

En una terminal:

```bash
python servidor_prueba.py --puerto 8000
```

(En Windows: segunda ventana de PowerShell, con el entorno activado.)

En `config.json`, cambiá el bloque de publicación:

```json
"publicacion": {
  "tipo": "http",
  "url": "http://localhost:8000/eventos",
  "buffer": "datos/pendientes.jsonl"
}
```

En otra terminal, `python -m vision_qr.main`.

### Probar el corte de red (QR-21)

1. Levantá el servidor con `--fallar`: rechaza todo.
2. Corré el escáner y escaneá etiquetas → se encolan en `datos/pendientes.jsonl`.
3. Reiniciá el servidor sin `--fallar`.
4. Escaneá una etiqueta más → se drena la cola y el Backend recibe todo,
   marcado como `REENVIADO`.

---

## 10. Medir la distancia máxima de lectura (QR-12)

```bash
python generar_etiquetas.py --ensayo-tamanos
```

Genera una hoja A4 con el mismo código en 30, 50, 70, 100 y 150 mm.
Imprimila **al 100%, sin "ajustar a página"**, pegala en la pared y alejá
la cámara midiendo hasta dónde lee cada tamaño.

Esa tabla define el tamaño definitivo de las etiquetas del warehouse.
Hacelo con la cámara del Rover, no con la webcam de la laptop: el resultado
depende del sensor y la óptica.

---

## 11. Migrar a la Raspberry Pi

Tiene su propia guía, porque en una Pi 3 sin pantalla cambian varias cosas
(sistema operativo, instalación, cámara, rendimiento):
**[raspberry-pi.md](raspberry-pi.md)**.

---

## 12. Estructura

Ver la sección "Estructura" del [README](../README.md).

---

## 13. Decisiones que conviene no revertir sin discutirlo

**El payload identifica la parada, no la describe.** Qué hay en cada
parada y qué debe hacer el Rover allí vive en la configuración y en el
Backend. Meterlo en la etiqueta impresa obliga a reimprimirla cada vez que
algo cambia. Además, el esquema corto usa 21x21 módulos contra 25x25 del
anterior: con la misma etiqueta de 10 cm, cada módulo es 19% más grande,
lo que se traduce en unos 19% más de distancia de lectura.

**El formato del payload vive en un solo archivo.** `generar_etiquetas.py`
importa `construir()` de `payload.py`. Si alguien duplica el formato, el
generador y el lector se desincronizan y nadie se entera hasta que hay
cincuenta etiquetas mal impresas pegadas en el warehouse.

**No se filtra por nitidez antes de decodificar.** Se probó y se descartó:
la varianza del laplaciano no discrimina los cuadros que fallan. Un cuadro
con barrido de movimiento que ZBar no lee puntúa *más alto* que uno con
poca luz que sí lee. Intentar decodificar es barato y no miente.

**El buffer escribe con `fsync` y reescribe de forma atómica.** Si el Rover
se queda sin batería a mitad de una escritura, no se corrompe la cola ni se
pierden eventos.

**Se dibuja el polígono de 4 puntos, no el rectángulo recto.** Con el Rover
en ángulo, el rectángulo miente sobre lo que el decodificador vio, y eso
confunde al diagnosticar.

**`lado_aparente` ya se calcula aunque no se use.** Es el insumo de la
estimación de distancia (QR-37) y sale gratis de las esquinas.

---

## 14. Qué falta

- Transporte MQTT detrás de la misma interfaz (QR-24)
- Latido de estado con métricas hacia el Dashboard (QR-23)
- Logs con rotación en lugar de `print` (QR-30)
- Estimación de pose y calibración de cámara (QR-36 a QR-38)
- Arranque automático como servicio en la Pi (QR-28), pendiente de validar en hardware
- Definir con el equipo de vehículos cómo consumen `accion` y `estado_local`

Hecho desde la versión anterior de esta guía: consulta local de la última
parada (QR-17, `estado_local`), política de paradas activas y mínimo, respaldo
de OpenCV desactivable, y pruebas automatizadas (`pytest`).
