"""Mide cuanto le cuesta a esta maquina leer un QR. No necesita camara.

Sirve para contestar "esto corre en una Raspberry Pi 3?" con un numero en
vez de una opinion, y para decidir con datos si conviene el respaldo de
OpenCV o bajar la resolucion.

Que mide, por cada resolucion:

    ZBar sin QR     cuadro vacio. Es el caso comun: la mayor parte del
                    tiempo el Rover no tiene ninguna etiqueta a la vista.
    ZBar con QR     cuadro con una etiqueta.
    OpenCV sin QR   lo que cuesta el respaldo en un cuadro vacio. El
                    respaldo corre siempre que ZBar no encuentra nada, o
                    sea, en casi todos los cuadros.

Limites, para no sacar conclusiones de mas:

  - Mide el DECODIFICADOR. No incluye captura, ni el bus USB, ni la red.
    El techo real de fps es menor. Para verlo entero: probar_camara.py.
  - Usa una escena sintetica. Con --cuadro se usa una foto real de la
    camara como fondo, que es bastante mas representativo.
  - Sirve para comparar configuraciones entre si, no como promesa.

Uso:
    python benchmark.py
    python benchmark.py --iteraciones 200
    python benchmark.py --cuadro camara_0.png      # foto real como fondo
    python benchmark.py --objetivo 15
"""

from __future__ import annotations
import argparse
import os
import platform
import shutil
import statistics as st
import subprocess
import sys
import time

import cv2
import numpy as np

from vision_qr.payload import construir


def _generar_qr(texto: str) -> np.ndarray:
    try:
        import qrcode
    except ImportError:
        sys.exit("Falta la libreria qrcode. Instalala con: pip install \"qrcode[pil]\"")
    q = qrcode.QRCode(box_size=10, border=4)
    q.add_data(texto)
    q.make(fit=True)
    img = np.array(q.make_image().convert("RGB"))
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def _fondo(ancho: int, alto: int, real=None) -> np.ndarray:
    """Escena sin QR. Si hay una foto real se usa esa; si no, textura suave
    con aspecto de pared o piso, que es mas exigente que un fondo plano."""
    if real is not None:
        return cv2.resize(real, (ancho, alto), interpolation=cv2.INTER_AREA)
    rng = np.random.default_rng(0)
    ruido = rng.integers(90, 200, (alto // 8 + 1, ancho // 8 + 1), dtype=np.uint8)
    suave = cv2.resize(ruido, (ancho, alto), interpolation=cv2.INTER_CUBIC)
    suave = cv2.GaussianBlur(suave, (0, 0), 3)
    return cv2.cvtColor(suave, cv2.COLOR_GRAY2BGR)


def _con_qr(fondo: np.ndarray, qr: np.ndarray) -> np.ndarray:
    alto, ancho = fondo.shape[:2]
    lado = int(alto * 0.45)
    etiqueta = cv2.resize(qr, (lado, lado), interpolation=cv2.INTER_NEAREST)
    salida = fondo.copy()
    y, x = (alto - lado) // 2, (ancho - lado) // 2
    salida[y:y + lado, x:x + lado] = etiqueta
    return salida


def _mediana_ms(fn, n: int) -> float:
    fn()  # calentamiento: la primera llamada paga inicializaciones
    tiempos = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        tiempos.append((time.perf_counter() - t) * 1000.0)
    return st.median(tiempos)


def _vcgencmd(*args) -> str | None:
    exe = shutil.which("vcgencmd")
    if not exe:
        return None
    try:
        return subprocess.run([exe, *args], capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        return None


_AHORA = {0x1: "subtension AHORA", 0x2: "frecuencia limitada AHORA",
          0x4: "CPU limitada AHORA", 0x8: "limite de temperatura AHORA"}
_HISTORICO = {0x10000: "subtension", 0x20000: "frecuencia limitada",
              0x40000: "limitacion de CPU", 0x80000: "limite de temperatura"}


def _leer_estado(texto: str | None) -> int | None:
    """Convierte 'throttled=0x50000' en un entero. None si no se puede."""
    if not texto:
        return None
    try:
        return int(texto.split("=")[-1], 16)
    except ValueError:
        return None


def evaluar_energia(antes: int, ahora: int):
    """Decide si la medicion se vio afectada por energia o temperatura.

    Los bits "desde el arranque" de get_throttled no se borran hasta
    reiniciar, y la Pi 3 suele registrar una subtension un instante al
    arrancar. Mirar solo el valor final marcaria como afectada una medicion
    perfectamente limpia. Por eso se compara contra el valor de ANTES de medir.

    Devuelve (veredicto, causas):
      "ok"        sin ningun aviso
      "previo"    hay avisos, pero de antes de la medicion (arranque)
      "afectado"  algo paso durante la medicion, o sigue pasando ahora
    """
    durante = [t for b, t in _AHORA.items() if ahora & b]
    durante += [f"hubo {t} durante la medicion"
                for b, t in _HISTORICO.items() if ahora & b and not antes & b]
    if durante:
        return "afectado", durante
    if ahora:
        return "previo", [f"hubo {t} antes de medir"
                          for b, t in _HISTORICO.items() if ahora & b]
    return "ok", []


def _modelo() -> str:
    try:
        with open("/proc/device-tree/model", "rb") as f:
            return f.read().decode("utf-8", "ignore").strip("\x00\n ")
    except OSError:
        return platform.processor() or platform.machine()


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark del decodificador QR")
    ap.add_argument("--iteraciones", type=int, default=100)
    ap.add_argument("--resoluciones", nargs="+", default=["320x240", "640x480", "1280x720"],
                    help="Lista tipo 640x480")
    ap.add_argument("--cuadro", default=None, help="Foto real de la camara para usar como fondo")
    ap.add_argument("--objetivo", type=float, default=10.0,
                    help="fps minimos que queremos (RNF-01 pide 10)")
    args = ap.parse_args()

    real = None
    if args.cuadro:
        real = cv2.imread(args.cuadro)
        if real is None:
            sys.exit(f"No pude leer la imagen {args.cuadro!r}")

    try:
        from pyzbar.pyzbar import decode, ZBarSymbol
    except ImportError as e:
        sys.exit(f"No se pudo cargar pyzbar/ZBar: {e}\n"
                 "En Linux: sudo apt install libzbar0  y  pip install pyzbar")

    print("=== equipo ===")
    print(f"modelo      : {_modelo()}")
    print(f"arquitectura: {platform.machine()}   nucleos: {os.cpu_count()}")
    print(f"python      : {platform.python_version()}   opencv: {cv2.__version__}")
    temp0 = _vcgencmd("measure_temp")
    estado_antes = _leer_estado(_vcgencmd("get_throttled"))
    if temp0:
        print(f"temperatura : {temp0.replace('temp=', '')} (antes de medir)")
    print(f"escena      : {'foto real ' + args.cuadro if real is not None else 'sintetica'}")
    print(f"iteraciones : {args.iteraciones} por medicion (se reporta la mediana)\n")

    qr = _generar_qr(construir("PA1"))
    detector = cv2.QRCodeDetector()

    filas = []
    for res in args.resoluciones:
        try:
            ancho, alto = (int(v) for v in res.lower().split("x"))
        except ValueError:
            sys.exit(f"Resolucion invalida {res!r}, usa el formato 640x480")

        vacio = _fondo(ancho, alto, real)
        lleno = _con_qr(vacio, qr)
        g_vacio = cv2.cvtColor(vacio, cv2.COLOR_BGR2GRAY)
        g_lleno = cv2.cvtColor(lleno, cv2.COLOR_BGR2GRAY)

        z_vacio = _mediana_ms(lambda: decode(g_vacio, symbols=[ZBarSymbol.QRCODE]), args.iteraciones)
        z_lleno = _mediana_ms(lambda: decode(g_lleno, symbols=[ZBarSymbol.QRCODE]), args.iteraciones)
        o_vacio = _mediana_ms(lambda: detector.detectAndDecodeMulti(vacio), args.iteraciones)

        # Un cuadro vacio con respaldo paga las dos cosas.
        fps_solo = 1000.0 / z_vacio
        fps_resp = 1000.0 / (z_vacio + o_vacio)
        filas.append((res, z_vacio, z_lleno, o_vacio, fps_solo, fps_resp))

    print("=== resultados (ms por cuadro, mediana) ===")
    print(f"{'resolucion':<11} {'ZBar vacio':>11} {'ZBar con QR':>12} {'OpenCV vacio':>13}"
          f" {'fps solo ZBar':>14} {'fps con respaldo':>17}")
    print("-" * 84)
    for res, zv, zc, ov, fs, fr in filas:
        print(f"{res:<11} {zv:>9.1f}ms {zc:>10.1f}ms {ov:>11.1f}ms {fs:>14.0f} {fr:>17.0f}")

    print(f"\n=== contra el objetivo de {args.objetivo:.0f} fps (solo el decodificador) ===")
    for res, zv, zc, ov, fs, fr in filas:
        a = "cumple" if fs >= args.objetivo else "NO cumple"
        b = "cumple" if fr >= args.objetivo else "NO cumple"
        print(f"{res:<11} solo ZBar: {a:<10} con respaldo: {b}")

    ratio = [ov / zv for _, zv, _, ov, _, _ in filas if zv > 0]
    if ratio:
        print(f"\nEl respaldo de OpenCV cuesta {min(ratio):.1f}x a {max(ratio):.1f}x lo que ZBar en un cuadro vacio.")
        print("Como casi todos los cuadros estan vacios, prenderlo multiplica el costo de casi cada cuadro.")
        print("En las pruebas de degradacion nunca leyo algo que ZBar no leyera: ver ensayo_robustez.py.")

    temp1 = _vcgencmd("measure_temp")
    estado_despues = _leer_estado(_vcgencmd("get_throttled"))
    if temp1:
        print(f"\ntemperatura despues: {temp1.replace('temp=', '')}")
    if estado_despues is not None:
        veredicto, causas = evaluar_energia(estado_antes or 0, estado_despues)
        codigo = f"0x{estado_despues:x}"
        if veredicto == "ok":
            print("estado de energia/temperatura: sin problemas (throttled=0x0)")
        elif veredicto == "previo":
            print(f"estado de energia/temperatura: sin problemas durante la medicion (throttled={codigo})")
            print(f"  Quedan avisos de antes de medir: {', '.join(causas)}.")
            print("  En la Pi 3 es habitual que la tension baje un instante al arrancar.")
            print("  Para ver cuando paso: sudo dmesg | grep -i voltage")
        else:
            print(f"ATENCION, la placa se limito ({codigo}): {', '.join(causas)}")
            print("Los numeros de arriba estan afectados. Revisa la fuente de alimentacion: la Pi 3 pide 5V/2.5A.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
