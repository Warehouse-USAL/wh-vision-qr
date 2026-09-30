"""Prueba minima: ver si la camara lee codigos QR. Nada mas.

Este es el primer script que hay que correr. No filtra nada, no publica
nada, no necesita configuracion: muestra CUALQUIER QR que entre en el
campo visual, sea del proyecto o no.

Por que existe separado de main.py: el modulo real descarta en silencio
todo QR que no empiece con el prefijo del proyecto (requisito RF-04, para
no reportar codigos de envases comerciales que anden dando vueltas por el
warehouse). Eso esta bien en produccion, pero al probar por primera vez
hace parecer que la camara no funciona. Aca se ve todo.

Uso:
    python probar_camara.py
    python probar_camara.py --indice 1
    python probar_camara.py --sin-ventana      # WSL2 o Pi sin escritorio
"""

from __future__ import annotations
import argparse
import time

import cv2

from vision_qr.captura import backend_por_defecto, _BACKENDS
from vision_qr.decodificador import Decodificador
from vision_qr.payload import interpretar, PayloadInvalido

VERDE = (0, 220, 0)      # QR del proyecto
AMARILLO = (0, 190, 255)  # QR ajeno, se lee pero no es nuestro


def _escalar_ventana(nombre: str, factor: float) -> None:
    """Agranda o achica la ventana sin tocar la resolucion de captura.

    Importante para no confundirse: esto solo cambia como se VE. Lo que
    la camara captura y lo que el decodificador procesa sigue siendo el
    mismo cuadro. Para capturar con mas detalle hay que subir --ancho y
    --alto, que si cuesta fps.
    """
    try:
        _, _, w, h = cv2.getWindowImageRect(nombre)
        if w > 0 and h > 0:
            cv2.resizeWindow(nombre, max(int(w * factor), 240), max(int(h * factor), 180))
    except Exception:
        pass  # no todos los backends de GUI lo soportan


def main() -> int:
    ap = argparse.ArgumentParser(description="Prueba de camara y lectura de QR")
    ap.add_argument("--indice", type=int, default=0)
    ap.add_argument("--ancho", type=int, default=640)
    ap.add_argument("--alto", type=int, default=480)
    ap.add_argument("--backend", default=None, help=f"Opciones: {list(_BACKENDS)}")
    ap.add_argument("--sin-ventana", action="store_true")
    ap.add_argument("--ventana", type=int, default=960, metavar="PX",
                    help="Ancho inicial de la ventana (no cambia la resolucion de captura)")
    ap.add_argument("--pantalla-completa", action="store_true",
                    help="Arrancar en pantalla completa")
    ap.add_argument("--fourcc", default=None, metavar="COD",
                    help="Codec a pedirle a la camara, ej: MJPG. Util en la Raspberry Pi")
    ap.add_argument("--sin-respaldo", action="store_true",
                    help="Solo ZBar, sin el detector de OpenCV en cascada (compara fps)")
    args = ap.parse_args()

    backend = _BACKENDS[args.backend.lower()] if args.backend else backend_por_defecto()
    cap = cv2.VideoCapture(args.indice, backend)
    if not cap.isOpened():
        print(f"No se pudo abrir la camara {args.indice}.\n")
        print("Que revisar:")
        print("  1. Cerra Teams, Zoom, OBS o la app Camara si estan abiertos.")
        print("  2. Windows: Configuracion > Privacidad y seguridad > Camara,")
        print("     activa 'Permitir que las aplicaciones de escritorio")
        print("     accedan a la camara'.")
        print("  3. Proba otro indice: python buscar_camaras.py --guardar")
        return 1

    if args.fourcc:
        # Antes que la resolucion: al reves, muchas camaras negocian mal.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*args.fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.ancho)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.alto)

    # Lo que la camara realmente acepto, que puede diferir de lo pedido. En
    # una Pi sin pantalla es la unica forma de enterarse de que se quedo en
    # un modo lento o con menos resolucion.
    w_real = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h_real = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps_cam = cap.get(cv2.CAP_PROP_FPS)
    codigo = int(cap.get(cv2.CAP_PROP_FOURCC))
    codec = "".join(chr((codigo >> (8 * i)) & 0xFF) for i in range(4)).strip() or "?"
    print(f"Camara negocio: {w_real}x{h_real} a {fps_cam:.0f} fps, codec {codec}"
          f"   (pedido: {args.ancho}x{args.alto}"
          f"{', ' + args.fourcc if args.fourcc else ''})")

    decod = Decodificador(usar_respaldo=not args.sin_respaldo)

    VENTANA = "Prueba de camara"
    if not args.sin_ventana:
        # WINDOW_NORMAL permite redimensionar con el mouse y poner
        # pantalla completa. Por defecto cv2.imshow usa WINDOW_AUTOSIZE,
        # que clava la ventana al tamano del cuadro capturado (640x480) y
        # no deja tocarla: ese es el recuadro chico.
        cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
        ancho_real = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or args.ancho
        alto_real = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or args.alto
        escala = args.ventana / max(ancho_real, 1)
        cv2.resizeWindow(VENTANA, args.ventana, int(alto_real * escala))
        if args.pantalla_completa:
            cv2.setWindowProperty(VENTANA, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    pantalla_completa = args.pantalla_completa

    print("Camara abierta. Mostrale cualquier codigo QR.")
    print("Sirve el de un envase, uno generado en una web, el de una factura.")
    print("\nTeclas:  f = pantalla completa    + / - = agrandar o achicar    q = salir")
    print("Tambien podes arrastrar el borde de la ventana con el mouse.\n")

    t0 = time.monotonic()
    n_cuadros = 0
    vistos = {}          # contenido -> veces leido
    ultimo_impreso = None

    try:
        while True:
            ok, cuadro = cap.read()
            if not ok:
                print("Se perdio la imagen de la camara.")
                break
            n_cuadros += 1

            lecturas = decod.leer(cuadro)

            for l in lecturas:
                vistos[l.contenido] = vistos.get(l.contenido, 0) + 1

                # Imprimir solo cuando cambia, para no inundar la consola
                if l.contenido != ultimo_impreso:
                    ultimo_impreso = l.contenido
                    try:
                        u = interpretar(l.contenido)
                        print(f"  [PARADA]   {l.contenido}  ->  {u}")
                    except PayloadInvalido:
                        texto = l.contenido
                        if len(texto) > 70:
                            texto = texto[:67] + "..."
                        print(f"  [ajeno]    {texto}")

                if not args.sin_ventana and len(l.esquinas) >= 4:
                    try:
                        interpretar(l.contenido)
                        color = VERDE
                    except PayloadInvalido:
                        color = AMARILLO
                    import numpy as np
                    pts = np.array(l.esquinas, dtype=np.int32).reshape(-1, 1, 2)
                    cv2.polylines(cuadro, [pts], True, color, 3)
                    x, y = l.esquinas[0]
                    etiqueta = l.contenido[:40]
                    cv2.putText(cuadro, etiqueta, (x, max(y - 12, 16)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            if not args.sin_ventana:
                fps = n_cuadros / max(time.monotonic() - t0, 0.001)
                estado = (f"{fps:.1f} fps   {cuadro.shape[1]}x{cuadro.shape[0]}   "
                          f"codigos distintos: {len(vistos)}")
                cv2.putText(cuadro, estado, (10, cuadro.shape[0] - 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
                cv2.putText(cuadro, "verde = del proyecto   amarillo = otro QR",
                            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
                cv2.imshow(VENTANA, cuadro)

                tecla = cv2.waitKey(1) & 0xFF
                if tecla in (ord("q"), 27):
                    break
                if tecla == ord("f"):
                    pantalla_completa = not pantalla_completa
                    cv2.setWindowProperty(
                        VENTANA, cv2.WND_PROP_FULLSCREEN,
                        cv2.WINDOW_FULLSCREEN if pantalla_completa else cv2.WINDOW_NORMAL)
                elif tecla in (ord("+"), ord("=")):
                    _escalar_ventana(VENTANA, 1.25)
                elif tecla in (ord("-"), ord("_")):
                    _escalar_ventana(VENTANA, 0.8)

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if not args.sin_ventana:
            cv2.destroyAllWindows()

    dur = max(time.monotonic() - t0, 0.001)
    print("\n--- resumen ---")
    print(f"cuadros capturados      : {n_cuadros}")
    print(f"fps promedio            : {n_cuadros / dur:.1f}")
    print(f"codigos distintos leidos: {len(vistos)}")
    for contenido, veces in sorted(vistos.items(), key=lambda x: -x[1]):
        texto = contenido if len(contenido) <= 60 else contenido[:57] + "..."
        print(f"    {veces:5d} lecturas  {texto}")

    if not vistos:
        print("\nNo se leyo ningun codigo. Cosas a probar:")
        print("  - Subi el brillo de la pantalla del celular al maximo.")
        print("  - Aleja o acerca el codigo: muy cerca tampoco enfoca.")
        print("  - Evita el reflejo: no lo pongas contra una ventana o lampara.")
        print("  - Verifica que estas usando la camara correcta:")
        print("    python buscar_camaras.py --guardar")
    else:
        print("\nLa camara lee QR correctamente. Ya podes seguir con el resto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
