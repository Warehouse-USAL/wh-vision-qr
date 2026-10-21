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

    # Hojas A4 para imprimir y pegar: codigo de 7 cm, una copia por riel
    # (EXT = riel exterior, INT = interior), los home una sola vez
    python generar_etiquetas.py --hoja-impresion

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

from vision_qr.payload import construir, PARADAS, SECUENCIA, CATALOGO, AUTOMATICA, MANUAL, DESCARGA, HOME

NOMBRE_TIPO = {AUTOMATICA: "AUTOMATICA", MANUAL: "MANUAL", DESCARGA: "DESCARGA", HOME: "HOME"}

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


def una_etiqueta(id_parada: str, lado_mm: float, con_pie: bool = True,
                 riel: str | None = None) -> Image.Image:
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
    etiqueta_tipo = NOMBRE_TIPO[tipo]

    dibujo.text((mm_a_px(2), lado_px + mm_a_px(1)), id_parada.upper(),
                fill="black", font=grande)
    dibujo.text((lado_px - mm_a_px(2), lado_px + mm_a_px(5)), etiqueta_tipo,
                fill="black", font=chica, anchor="ra")
    if riel:
        # Mismo contenido en las dos copias: la marca sirve solo para no
        # pegar la del riel interior en el exterior (y viceversa).
        dibujo.text((lado_px - mm_a_px(2), lado_px + mm_a_px(9.5)), f"RIEL {riel}",
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
            "orden": SECUENCIA.index(pid) + 1 if pid in SECUENCIA else "",
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
    posicion = {p: i for i, p in enumerate(CATALOGO)}
    todas = sorted(previas.values(), key=lambda r: posicion.get(r["parada"], len(CATALOGO)))

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
    """Todas las etiquetas del catalogo en una hoja A4.

    Para probar en el escritorio: se imprime una sola hoja, o se abre en
    pantalla y se le muestran al Rover una por una sin gastar papel.
    Van en tres columnas para que las nueve entren en una hoja.
    """
    destino.mkdir(parents=True, exist_ok=True)
    ancho, alto = mm_a_px(210), mm_a_px(297)
    hoja = Image.new("RGB", (ancho, alto), "white")
    dibujo = ImageDraw.Draw(hoja)
    titulo = cargar_fuente(mm_a_px(6))
    dibujo.text((mm_a_px(15), mm_a_px(10)), f"Recorrido del Rover - {len(CATALOGO)} paradas",
                fill="black", font=titulo)

    columnas = 3
    sep = (210 - 2 * 15 - columnas * lado_mm) / max(columnas - 1, 1)
    col_x = [mm_a_px(15 + i * (lado_mm + sep)) for i in range(columnas)]
    y = mm_a_px(25)
    for i, pid in enumerate(CATALOGO):
        img = una_etiqueta(pid, lado_mm)
        hoja.paste(img, (col_x[i % columnas], y))
        if i % columnas == columnas - 1:
            y += img.height + mm_a_px(8)

    salida = destino / "hoja_prueba_A4.png"
    hoja.save(salida, dpi=(DPI, DPI))
    print(f"Hoja de prueba con las {len(CATALOGO)} paradas: {salida}")
    print("Imprimila al 100%, o abrila en pantalla para probar sin gastar papel.")


def lado_imagen_para_codigo(codigo_mm: float) -> float:
    """Lado de la imagen para que el CODIGO (los modulos) mida codigo_mm.

    El lado de una etiqueta incluye la zona blanca de silencio (4 modulos
    por lado). El layout pide un QR de 7 x 7 cm: se interpreta como el
    codigo en si, asi que la imagen impresa es algo mayor.
    """
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, box_size=10, border=4)
    qr.add_data(construir("PA1"))
    qr.make(fit=True)
    n = qr.modules_count
    return codigo_mm * (n + 8) / n


def hoja_impresion(destino: Path, codigo_mm: float = 70, copias: int = 2) -> int:
    """Hojas A4 listas para imprimir al 100 % y recortar.

    Con dos rieles, cada vehiculo lee un QR pegado junto a SU linea:
    copias=2 imprime cada parada del circuito dos veces (EXT e INT). Los home
    son de un solo vehiculo y salen una vez. Devuelve cuantas etiquetas hay.
    """
    if copias not in (1, 2):
        raise ValueError("copias tiene que ser 1 o 2")
    destino.mkdir(parents=True, exist_ok=True)

    items = []
    for pid in CATALOGO:
        if PARADAS[pid] == HOME or copias == 1:
            items.append((pid, None))
        else:
            items += [(pid, "EXT"), (pid, "INT")]

    lado = lado_imagen_para_codigo(codigo_mm)
    ancho, alto = mm_a_px(210), mm_a_px(297)
    margen, hueco = mm_a_px(5), mm_a_px(3)
    ejemplo = una_etiqueta("PA1", lado)
    celda_w, celda_h = ejemplo.width, ejemplo.height
    cols = max(1, (ancho - 2 * margen + hueco) // (celda_w + hueco))
    filas = max(1, (alto - 2 * margen - mm_a_px(8) + hueco) // (celda_h + hueco))
    por_hoja = cols * filas

    hojas = []
    for ini in range(0, len(items), por_hoja):
        hoja = Image.new("RGB", (ancho, alto), "white")
        d = ImageDraw.Draw(hoja)
        d.text((margen, margen // 2), "Imprimir al 100% (sin ajustar a pagina). "
               f"Codigo de {codigo_mm:g} mm. Recortar por el borde gris.",
               fill="black", font=cargar_fuente(mm_a_px(3.2)))
        for k, (pid, riel) in enumerate(items[ini:ini + por_hoja]):
            x = margen + (k % cols) * (celda_w + hueco)
            y = margen + mm_a_px(8) + (k // cols) * (celda_h + hueco)
            hoja.paste(una_etiqueta(pid, lado, riel=riel), (x, y))
            d.rectangle([x, y, x + celda_w - 1, y + celda_h - 1], outline=(170, 170, 170), width=2)
        hojas.append(hoja)

    for i, h in enumerate(hojas, 1):
        h.save(destino / f"hoja_impresion_{i}.png", dpi=(DPI, DPI))
    Image.init()   # carga los plugins (el PDF usa JPEG) en instalaciones de Pillow recortadas
    hojas[0].save(destino / "hoja_impresion.pdf", save_all=True, append_images=hojas[1:],
                  resolution=DPI)
    print(f"{len(items)} etiquetas en {len(hojas)} hoja(s) A4: {destino / 'hoja_impresion.pdf'}")
    print(f"Cada imagen mide {lado:.0f} mm de lado (el codigo, {codigo_mm:g} mm, mas la zona blanca).")
    return len(items)


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
                    help=f"Cuales generar. Por defecto todas: {' '.join(CATALOGO)}")
    ap.add_argument("--mm", type=float, default=100.0, help="Lado del codigo en milimetros")
    ap.add_argument("--destino", default="etiquetas")
    ap.add_argument("--hoja-prueba", action="store_true",
                    help="Una hoja A4 con todas, para probar sin imprimir de a una")
    ap.add_argument("--hoja-impresion", action="store_true",
                    help="Hojas A4 (PDF y PNG) con una copia por riel, para imprimir y pegar")
    ap.add_argument("--codigo-mm", type=float, default=70.0,
                    help="Lado del codigo en --hoja-impresion (el layout pide 70)")
    ap.add_argument("--copias", type=int, default=2, choices=[1, 2],
                    help="En --hoja-impresion: 2 = una por riel (EXT e INT)")
    ap.add_argument("--ensayo-tamanos", action="store_true",
                    help="Hoja A4 con el mismo codigo en varios tamanos")
    args = ap.parse_args()

    destino = Path(args.destino)

    if args.ensayo_tamanos:
        ensayo_tamanos(destino)
        return
    if args.hoja_impresion:
        hoja_impresion(destino, args.codigo_mm, args.copias)
        return
    if args.hoja_prueba:
        hoja_prueba(destino)
        return

    paradas = args.paradas if args.paradas else CATALOGO
    desconocidas = [p for p in paradas if p.upper() not in PARADAS]
    if desconocidas:
        raise SystemExit(
            f"Paradas desconocidas: {', '.join(desconocidas)}.\n"
            f"Validas: {', '.join(CATALOGO)}"
        )

    generar(paradas, args.mm, destino)


if __name__ == "__main__":
    main()
