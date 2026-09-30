"""Generador de etiquetas QR del recorrido (QR-06).

El formato del contenido lo define vision_qr/payload.py, no este archivo.
Asi no hay forma de que el generador y el lector se desincronicen, que es
el error que deja cincuenta etiquetas mal impresas pegadas en el circuito.

Ejemplos:
    # Las seis etiquetas del recorrido, 10 cm de lado
    python generar_etiquetas.py

    # Mas grandes, para leer desde mas lejos
    python generar_etiquetas.py --mm 150

    # Solo algunas, para reimprimir una que se arruino
    python generar_etiquetas.py --paradas PA2 PM3

    # Hoja A4 con las seis, para probar sin imprimir de a una
    python generar_etiquetas.py --hoja-prueba

    # Hoja A4 con el mismo codigo en varios tamanos, para medir
    # la distancia maxima de lectura (QR-12)
    python generar_etiquetas.py --ensayo-tamanos
"""

from __future__ import annotations
import argparse
import csv
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_Q
from PIL import Image, ImageDraw, ImageFont

from vision_qr.payload import construir, PARADAS, SECUENCIA, AUTOMATICA

DPI = 300

# Windows no trae DejaVu; sin esta cadena de respaldo el pie de la etiqueta
# sale en el tipo por defecto de PIL, que es un bitmap diminuto e ilegible
# al imprimir.
FUENTES = ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arialbd.ttf", "arial.ttf",
           "Arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
           "segoeui.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"]


def cargar_fuente(px: int):
    for nombre in FUENTES:
        try:
            return ImageFont.truetype(nombre, px)
        except OSError:
            continue
    return ImageFont.load_default()


def mm_a_px(mm: float) -> int:
    return int(round(mm / 25.4 * DPI))


def una_etiqueta(id_parada: str, lado_mm: float, con_pie: bool = True) -> Image.Image:
    """Genera una etiqueta lista para imprimir.

    Correccion de errores nivel Q: tolera suciedad, sombras y deterioro
    parcial, que es exactamente lo que le pasa a una etiqueta pegada a la
    altura de un Rover que circula todos los dias.
    """
    texto = construir(id_parada)

    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, box_size=10, border=4)
    qr.add_data(texto)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    lado_px = mm_a_px(lado_mm)
    img = img.resize((lado_px, lado_px), Image.NEAREST)

    if not con_pie:
        return img

    alto_pie = mm_a_px(14)
    lienzo = Image.new("RGB", (lado_px, lado_px + alto_pie), "white")
    lienzo.paste(img, (0, 0))
    dibujo = ImageDraw.Draw(lienzo)

    # El identificador grande y legible a simple vista permite verificar
    # que la etiqueta pegada corresponde al plano, sin escanear nada. Es la
    # defensa mas barata contra pegarla en el lugar equivocado, que el
    # software no puede detectar por si solo.
    grande = cargar_fuente(mm_a_px(9))
    chica = cargar_fuente(mm_a_px(3.2))
    tipo = PARADAS[id_parada.upper()]
    etiqueta_tipo = "AUTOMATICA" if tipo == AUTOMATICA else "MANUAL"

    dibujo.text((mm_a_px(2), lado_px + mm_a_px(1)), id_parada.upper(),
                fill="black", font=grande)
    dibujo.text((lado_px - mm_a_px(2), lado_px + mm_a_px(5)), etiqueta_tipo,
                fill="black", font=chica, anchor="ra")
    return lienzo


CAMPOS_MAPA = ["parada", "tipo", "orden", "contenido", "archivo", "lado_mm", "instalada", "verificada"]


def _leer_mapa(ruta: Path) -> dict:
    """Filas del mapa que ya existe, por parada. Si no existe o esta roto, vacio."""
    if not ruta.exists():
        return {}
    try:
        with ruta.open(newline="", encoding="utf-8") as f:
            return {fila["parada"]: fila for fila in csv.DictReader(f) if fila.get("parada")}
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}


def generar(paradas, lado_mm: float, destino: Path):
    destino.mkdir(parents=True, exist_ok=True)
    filas = []
    for pid in paradas:
        pid = pid.upper()
        texto = construir(pid)
        nombre = f"{pid}.png"
        una_etiqueta(pid, lado_mm).save(destino / nombre, dpi=(DPI, DPI))
        filas.append({
            "parada": pid,
            "tipo": PARADAS[pid],
            "orden": SECUENCIA.index(pid) + 1,
            "contenido": texto,
            "archivo": nombre,
            "lado_mm": lado_mm,
            "instalada": "NO",
            "verificada": "NO",
        })

    # El mapa de correspondencias es tan importante como las etiquetas: es
    # lo unico que permite auditar que cada una quedo pegada donde debia.
    #
    # Se FUSIONA con el que ya existe, no se sobrescribe. Reimprimir una sola
    # etiqueta (--paradas PM3) no puede borrar el registro de las otras cinco:
    # ese registro se llena a mano, con cinta metrica y en el lugar, y es lo
    # unico que no se puede regenerar.
    #
    # Las etiquetas que se generan ahora vuelven a NO/NO: son papel nuevo que
    # todavia no esta pegado ni verificado, aunque la anterior si lo estuviera.
    mapa = destino / "mapa_etiquetas.csv"
    previas = _leer_mapa(mapa)
    reiniciadas = [
        f["parada"] for f in filas
        if previas.get(f["parada"], {}).get("instalada", "NO").strip().upper() == "SI"
    ]
    for f in filas:
        previas[f["parada"]] = f
    posicion = {p: i for i, p in enumerate(SECUENCIA)}
    todas = sorted(previas.values(), key=lambda r: posicion.get(r["parada"], len(SECUENCIA)))

    try:
        with mapa.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS_MAPA, extrasaction="ignore", restval="")
            w.writeheader()
            w.writerows(todas)
    except PermissionError:
        raise SystemExit(
            f"\nNo pude escribir {mapa}. Si lo tenes abierto en Excel, cerralo y volve a correr.\n"
            "Las imagenes de las etiquetas ya se generaron."
        )

    print(f"{len(filas)} etiquetas de {lado_mm:.0f} mm en {destino}/\n")
    for f in filas:
        print(f"    {f['parada']}   {f['tipo']:11} orden {f['orden']}   {f['contenido']}")
    print(f"\nmapa de correspondencias: {mapa}  ({len(todas)} paradas registradas)")
    if reiniciadas:
        print(f"OJO: {', '.join(reiniciadas)} estaba(n) marcada(s) como instalada(s). Al generarla(s) de "
              "nuevo vuelve(n) a NO: la etiqueta nueva todavia hay que pegarla y verificarla.")
    print("Completa 'instalada' y 'verificada' al pegarlas en el circuito.")


def hoja_prueba(destino: Path, lado_mm: float = 45):
    """Las seis etiquetas en una hoja A4.

    Para probar en el escritorio: se imprime una sola hoja, o se abre en
    pantalla y se le muestran al Rover una por una sin gastar papel.
    """
    destino.mkdir(parents=True, exist_ok=True)
    ancho, alto = mm_a_px(210), mm_a_px(297)
    hoja = Image.new("RGB", (ancho, alto), "white")
    dibujo = ImageDraw.Draw(hoja)
    titulo = cargar_fuente(mm_a_px(6))
    dibujo.text((mm_a_px(15), mm_a_px(10)), "Recorrido del Rover - 6 paradas",
                fill="black", font=titulo)

    col_x = [mm_a_px(20), mm_a_px(115)]
    y = mm_a_px(25)
    for i, pid in enumerate(SECUENCIA):
        img = una_etiqueta(pid, lado_mm)
        hoja.paste(img, (col_x[i % 2], y))
        if i % 2 == 1:
            y += img.height + mm_a_px(8)

    salida = destino / "hoja_prueba_A4.png"
    hoja.save(salida, dpi=(DPI, DPI))
    print(f"Hoja de prueba con las 6 paradas: {salida}")
    print("Imprimila al 100%, o abrila en pantalla para probar sin gastar papel.")


def ensayo_tamanos(destino: Path):
    """Hoja unica con el mismo codigo en varios tamanos.

    Se imprime, se pega en la pared y se aleja el Rover hasta que cada
    tamano deja de leerse. Da la tabla de distancia maxima por tamano que
    pide QR-12, en una sola sesion.
    """
    destino.mkdir(parents=True, exist_ok=True)
    tamanos = [30, 50, 70, 100, 150]
    ancho, alto = mm_a_px(210), mm_a_px(297)
    hoja = Image.new("RGB", (ancho, alto), "white")
    dibujo = ImageDraw.Draw(hoja)
    fuente = cargar_fuente(mm_a_px(5))

    y = mm_a_px(10)
    for t in tamanos:
        img = una_etiqueta("PA1", t, con_pie=False)
        hoja.paste(img, (mm_a_px(10), y))
        dibujo.text((mm_a_px(10) + img.width + mm_a_px(6), y + mm_a_px(4)),
                    f"{t} mm", fill="black", font=fuente)
        y += img.height + mm_a_px(6)
        if y > alto - mm_a_px(20):
            break

    salida = destino / "ensayo_tamanos_A4.png"
    hoja.save(salida, dpi=(DPI, DPI))
    print(f"Hoja de ensayo: {salida}")
    print("Imprimila al 100% (sin 'ajustar a pagina') y medi la distancia")
    print("maxima de cada tamano CON LA CAMARA DEL ROVER, no con la webcam.")


def main():
    ap = argparse.ArgumentParser(description="Generador de etiquetas QR - Warehouse USAL")
    ap.add_argument("--paradas", nargs="+", default=None,
                    help=f"Cuales generar. Por defecto las seis: {' '.join(SECUENCIA)}")
    ap.add_argument("--mm", type=float, default=100.0, help="Lado del codigo en milimetros")
    ap.add_argument("--destino", default="etiquetas")
    ap.add_argument("--hoja-prueba", action="store_true",
                    help="Una hoja A4 con las seis, para probar sin imprimir de a una")
    ap.add_argument("--ensayo-tamanos", action="store_true",
                    help="Hoja A4 con el mismo codigo en varios tamanos")
    args = ap.parse_args()

    destino = Path(args.destino)

    if args.ensayo_tamanos:
        ensayo_tamanos(destino)
        return
    if args.hoja_prueba:
        hoja_prueba(destino)
        return

    paradas = args.paradas if args.paradas else SECUENCIA
    desconocidas = [p for p in paradas if p.upper() not in PARADAS]
    if desconocidas:
        raise SystemExit(
            f"Paradas desconocidas: {', '.join(desconocidas)}.\n"
            f"Validas: {', '.join(SECUENCIA)}"
        )

    generar(paradas, args.mm, destino)


if __name__ == "__main__":
    main()
