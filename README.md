# wh-vision-qr

Módulo de visión del Rover del Warehouse USAL. Lee los códigos QR pegados en
las paradas del circuito para que el vehículo sepa dónde está, y publica cada
lectura hacia el servidor.

Todo el procesamiento ocurre **a bordo del Rover**: por la red viaja solo el
dato decodificado, nunca video.

```
cámara → ZBar (decodifica) → valida que sea del proyecto → confirma en N cuadros
       → política de paradas → evento → red (con buffer en disco) + archivo local
```

## El circuito

Seis paradas fijas en forma de U. Cada una tiene un QR que dice cuál es:

```
PA1 → PA2 → PA3 → PM1 → PM2 → PM3 → (vuelve a PA1)

PA1 PA2 PA3   automáticas: el Rover se detiene solo
PM1 PM2 PM3   manuales:    requieren un operador
```

El contenido de la etiqueta es `WH2|PA1`: prefijo del proyecto, versión del
esquema y parada. **El QR identifica el lugar, no el producto**: qué hay en cada
parada vive en la base de datos del Backend, así que cambiar el stock nunca
obliga a reimprimir una etiqueta.

## Inicio rápido

Desde la raíz del repositorio. Necesita Python 3.10 o superior.

**Windows (PowerShell)**

```powershell
py -m venv .env
.env\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Linux**

```bash
sudo apt install -y libzbar0 python3-venv
python3 -m venv .env && source .env/bin/activate
pip install -r requirements.txt
```

Después:

```
python probar_camara.py                 # ¿la cámara lee QR? Muestra cualquier código
python generar_etiquetas.py --hoja-prueba
copy config.example.json config.json    # en Linux: cp
python -m vision_qr.main
```

Más detalle, entornos alternativos y solución de problemas en
[docs/guia-de-desarrollo.md](docs/guia-de-desarrollo.md).

## Política de paradas

No siempre el Rover tiene que detenerse en las seis. En `config.json`:

```json
"paradas_activas": ["PA1", "PM2"],
"minimo_paradas": 0
```

| `paradas_activas` | `minimo_paradas` | Significa |
|---|---|---|
| `null` | `0` | las seis (comportamiento base) |
| `["PA1","PM2"]` | `0` | esas dos, y solo esas |
| `null` | `4` | cuatro cualesquiera de las seis |
| `["PA1","PA2","PA3","PM1"]` | `3` | tres cualesquiera de esas cuatro |

Cada evento lleva una `accion` recomendada (`detener`, `esperar_operador` o
`continuar`). **El módulo no frena al Rover**: recomienda, y quien controla los
motores decide si puede cumplirlo. Una parada inactiva se lee y se reporta igual.

## Configuración

| Clave | Por defecto | Qué hace |
|---|---|---|
| `id_rover` | `rover-sin-nombre` | Identifica al vehículo en cada evento |
| `mostrar_ventana` | `true` | `false` en la Raspberry Pi sin pantalla |
| `cuadros_para_confirmar` | `3` | Cuadros seguidos con el mismo código antes de emitir |
| `segundos_para_reemitir` | `5.0` | Cuánto debe desaparecer una etiqueta para contar como nueva |
| `usar_respaldo_opencv` | `true` | Detector de OpenCV en cascada. **Apagado en `config.pi.json`**: ver docs/raspberry-pi.md |
| `paradas_activas` | `null` | Dónde puede detenerse |
| `minimo_paradas` | `0` | Cuántas hacen falta. `0` = todas las activas |
| `estado_local` | `null` | Archivo JSON con la última parada, para el código de navegación |
| `secuencia_recorrido` | las seis | Orden esperado. Se filtra por `paradas_activas` |
| `recorrido_circular` | `true` | Si tras la última se espera volver a la primera |
| `captura.tipo` | `webcam` | `webcam`, `video`, `archivos`, `red` o `picamera` |
| `publicacion.tipo` | `consola` | `consola` o `http` |
| `publicacion.buffer` | — | Archivo donde se guardan los eventos si se corta la red |

`config.example.json` es para la laptop y `config.pi.json` para la Raspberry
Pi. `config.pi-clip.json` es para medir la Pi sin cámara, con un clip grabado;
`config.pi-red.json`, para leer la cámara de la laptop por la red.
`config.json` es de cada máquina y no se versiona.

## Herramientas

| Script | Para qué |
|---|---|
| `probar_camara.py` | Primera prueba. Muestra cualquier QR, sin filtrar |
| `buscar_camaras.py` | Lista las cámaras y sus índices; `--guardar` deja una foto de cada una |
| `generar_etiquetas.py` | Genera las etiquetas y mantiene el mapa de correspondencias |
| `transmitir_camara.py` | Emite la cámara de la laptop por la red, para probar la Pi en vivo |
| `grabar_clip.py` | Graba un clip para reproducirlo después como si fuera la cámara |
| `benchmark.py` | Mide cuánto le cuesta al equipo leer un QR. No necesita cámara |
| `ensayo_robustez.py` | Compara ZBar contra OpenCV en catorce condiciones degradadas |
| `servidor_prueba.py` | Backend simulado, para probar sin depender de otro grupo |

`python -m vision_qr.main --reporte reportes/prueba.json --etiqueta "nota"`
guarda un resumen de la sesión (cobertura, fps, paradas sin leer) para comparar
corridas entre sí.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

Incluyen pruebas de punta a punta que ejecutan el programa con imágenes en
lugar de cámara. Si `libzbar0` no está instalado, las que lo necesitan se
saltean en vez de fallar.

## Raspberry Pi

Guía completa en [docs/raspberry-pi.md](docs/raspberry-pi.md): sistema
operativo, instalación, cámara, medición de rendimiento y arranque automático.

## Contrato con los demás grupos

[docs/contrato-de-evento.md](docs/contrato-de-evento.md): el evento que se
publica, qué campos son nuevos y qué falta acordar con Backend.

## Estructura

```
vision_qr/
  captura.py        Fuentes de imagen: webcam, video, archivos, picamera
  decodificador.py  ZBar + respaldo de OpenCV; devuelve las cuatro esquinas
  payload.py        Contenido de las etiquetas y catálogo de paradas
  confirmador.py    Confirmación por N cuadros y deduplicación
  recorrido.py      Orden esperado de paradas y detección de saltos
  mision.py         Política de paradas: activas y mínimo
  publicador.py     Transporte, buffer offline y estado local
  main.py           Bucle principal
tests/              pytest
docs/               Guías y contrato del evento
```

## Decisiones que conviene no revertir sin discutirlas

**El formato de la etiqueta vive en un solo archivo** (`payload.py`). El
generador importa `construir()` de ahí. Si alguien duplica el formato, el
generador y el lector se desincronizan y nadie se entera hasta que hay
etiquetas mal impresas pegadas en el circuito.

**Un cambio en `payload.py` puede invalidar etiquetas ya pegadas.** Por eso el
esquema lleva versión y `test_payload.py` fija el formato impreso.

**Los avisos de orden no rechazan lecturas, solo las marcan.** Un salto puede
ser legítimo, y descartar una lectura correcta es peor que registrarla con una
advertencia.

**El buffer preserva el orden.** Al volver la red se vacía la cola vieja antes
de enviar el evento nuevo. Escribe con `fsync` y reemplaza de forma atómica:
un corte de energía a mitad de escritura no corrompe la cola.

**No se filtra por nitidez antes de decodificar.** Se probó y se descartó: la
varianza del laplaciano no discrimina los cuadros que fallan. Un cuadro con
barrido de movimiento que ZBar no lee puntúa *más alto* que uno con poca luz
que sí lee.

**El mapa de etiquetas se fusiona, no se sobrescribe.** Es lo único que no se
puede regenerar: se llena a mano al pegar cada etiqueta.

## Pendiente

- Transporte MQTT detrás de la misma interfaz
- Latido de estado con métricas hacia el Dashboard
- Estimación de pose y calibración de cámara
- Validar en hardware el arranque automático como servicio
- Definir con vehículos cómo consumen `accion` y `estado_local`
