"""Graba un clip desde la camara, para reproducirlo despues.

Para que sirve:

  1. Desarrollar en Linux (WSL2, maquina virtual) sin pelearse con el
     pasaje de la camara: grabas una vez en Windows y reproduces el clip
     cuantas veces quieras del otro lado.

  2. Volver reproducibles las pruebas. Un clip del Rover avanzando por el
     pasillo es la unica forma honesta de medir la tasa de acierto con
     barrido real, y se puede volver a correr identico despues de cada
     cambio en el codigo.

  3. Documentar una falla. Cuando una etiqueta no se lea en el warehouse,
     grabar el clip vale mas que describir el problema por escrito.

Uso:
    python grabar_clip.py                          # 10 s desde la camara 0
    python grabar_clip.py --segundos 30 --salida pasillo_A.mp4
    python grabar_clip.py --indice 1 --ancho 1280 --alto 720
"""

from __future__ import annotations
import argparse
import time
from pathlib import Path

import cv2

from vision_qr.captura import backend_por_defecto, _BACKENDS


def main():
    ap = argparse.ArgumentParser(description="Grabador de clips - Warehouse USAL")
    ap.add_argument("--indice", type=int, default=0)
    ap.add_argument("--segundos", type=float, default=10.0)
    ap.add_argument("--salida", default="clips/clip.mp4")
    ap.add_argument("--ancho", type=int, default=640)
    ap.add_argument("--alto", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--backend", default=None, help=f"Opciones: {list(_BACKENDS)}")
    ap.add_argument("--sin-ventana", action="store_true")
    args = ap.parse_args()

    backend = _BACKENDS[args.backend.lower()] if args.backend else backend_por_defecto()

    cap = cv2.VideoCapture(args.indice, backend)
    if not cap.isOpened():
        print(f"No se pudo abrir la camara {args.indice}.")
        print("Proba primero con: python buscar_camaras.py --guardar")
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.ancho)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.alto)
    cap.set(cv2.CAP_PROP_FPS, args.fps)

    ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or args.ancho
    alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or args.alto

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)

    # mp4v esta disponible sin dependencias extra en las tres plataformas.
    # No es el codec mas eficiente, pero para clips cortos no importa y
    # evita que alguien tenga que instalar nada.
    escritor = cv2.VideoWriter(str(salida), cv2.VideoWriter_fourcc(*"mp4v"),
                               args.fps, (ancho, alto))
    if not escritor.isOpened():
        print(f"No se pudo crear el archivo {salida}.")
        cap.release()
        return 1

    print(f"Grabando {args.segundos:.0f} s a {ancho}x{alto} en {salida}")
    print("Ctrl+C o 'q' para cortar antes.\n")

    t0 = time.monotonic()
    n = 0
    try:
        while time.monotonic() - t0 < args.segundos:
            ok, cuadro = cap.read()
            if not ok:
                break
            escritor.write(cuadro)
            n += 1

            restante = args.segundos - (time.monotonic() - t0)
            if not args.sin_ventana:
                vista = cuadro.copy()
                cv2.putText(vista, f"REC  {restante:4.1f} s   {n} cuadros",
                            (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                cv2.imshow("Grabando - 'q' para cortar", vista)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
            elif n % 30 == 0:
                print(f"  {restante:4.1f} s restantes...")
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        escritor.release()
        if not args.sin_ventana:
            cv2.destroyAllWindows()

    dur = time.monotonic() - t0
    print(f"\nListo: {salida}  ({n} cuadros, {dur:.1f} s, {n/max(dur,0.01):.1f} fps reales)")
    print("\nPara reproducirlo, en config.json:")
    print(f'  "captura": {{ "tipo": "video", "ruta": "{salida.as_posix()}", "repetir": false }}')
    print("\nOpciones utiles:")
    print('  "velocidad": 0     reproduce lo mas rapido posible (mide el techo del pipeline)')
    print('  "repetir": true    repite en bucle')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
