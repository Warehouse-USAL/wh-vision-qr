"""Bucle principal del modulo de vision QR.

Uso:
    python -m vision_qr.main                     # usa config.json
    python -m vision_qr.main --config otro.json
    python -m vision_qr.main --sin-ventana       # sin interfaz grafica
"""

from __future__ import annotations
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

from .captura import construir_fuente
from .decodificador import Decodificador, anotar
from .payload import interpretar, PayloadInvalido, SECUENCIA
from .confirmador import Confirmador
from .recorrido import Recorrido
from .mision import Mision, ConfiguracionInvalida
from .vista_web import VistaWeb
from .publicador import construir_publicador, construir_evento, escribir_estado_local


def escalar_ventana(nombre: str, factor: float) -> None:
    """Agranda o achica la ventana sin tocar la resolucion de captura."""
    try:
        _, _, w, h = cv2.getWindowImageRect(nombre)
        if w > 0 and h > 0:
            cv2.resizeWindow(nombre, max(int(w * factor), 240), max(int(h * factor), 180))
    except Exception:
        pass


def cargar_config(ruta: str) -> dict:
    p = Path(ruta)
    if not p.exists():
        print(f"No existe el archivo de configuracion {ruta!r}.", file=sys.stderr)
        print("Copia config.example.json a config.json y ajustalo.", file=sys.stderr)
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Escaner QR del Rover - Warehouse USAL")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--sin-ventana", action="store_true",
                    help="No abrir ventana de video (para Pi sin escritorio)")
    ap.add_argument("--reporte", default=None, metavar="ARCHIVO.json",
                    help="Guarda el resumen de la sesion, para comparar corridas")
    ap.add_argument("--etiqueta", default=None,
                    help="Nota que se guarda en el reporte, ej: 'velocidad baja, con luz'")
    ap.add_argument("--ventana", type=int, default=960, metavar="PX",
                    help="Ancho inicial de la ventana (no cambia la resolucion de captura)")
    ap.add_argument("--pantalla-completa", action="store_true",
                    help="Arrancar en pantalla completa")
    ap.add_argument("--vista-web", type=int, nargs="?", const=8080, default=None, metavar="PUERTO",
                    help="Publica el video con los QR marcados en http://<ip>:PUERTO/ "
                         "(por defecto 8080). Para ver la camara de una Pi sin pantalla")
    args = ap.parse_args()

    cfg = cargar_config(args.config)
    id_rover = cfg.get("id_rover", "rover-sin-nombre")
    mostrar = cfg.get("mostrar_ventana", True) and not args.sin_ventana

    fuente = construir_fuente(cfg["captura"])
    decod = Decodificador(usar_respaldo=cfg.get("usar_respaldo_opencv", True))
    conf = Confirmador(
        cuadros_necesarios=cfg.get("cuadros_para_confirmar", 3),
        segundos_reemision=cfg.get("segundos_para_reemitir", 5.0),
    )
    pub = construir_publicador(cfg["publicacion"])

    cfg_vista = cfg.get("vista_web") or {}
    puerto_vista = args.vista_web if args.vista_web is not None else cfg_vista.get("puerto")
    vista = None
    if puerto_vista:
        try:
            vista = VistaWeb(int(puerto_vista), fps_max=cfg_vista.get("fps_max", 8.0),
                             calidad=cfg_vista.get("calidad", 70))
        except OSError as e:
            print(f"No se pudo abrir la vista web en el puerto {puerto_vista}: {e}", file=sys.stderr)
            return 1

    try:
        mision = Mision(cfg.get("paradas_activas"), cfg.get("minimo_paradas", 0))
    except ConfiguracionInvalida as e:
        print(f"Configuracion invalida: {e}", file=sys.stderr)
        return 1

    # El recorrido esperado es el orden del circuito filtrado por las
    # paradas activas. Asi, una parada en la que el Rover no debe detenerse
    # nunca aparece como "sin leer" ni dispara una advertencia falsa; y el
    # filtro aplica aunque el config.json viejo traiga las seis listadas.
    base = cfg.get("secuencia_recorrido") or SECUENCIA
    ruta = Recorrido(
        secuencia=[p for p in base if mision.es_activa(p)],
        circular=cfg.get("recorrido_circular", True),
    )
    estado_local = cfg.get("estado_local")
    aviso_estado = False

    print(f"Rover: {id_rover}")
    print(f"Fuente: {cfg['captura'].get('tipo')}   Transporte: {cfg['publicacion'].get('tipo')}")
    print(f"Confirmacion: {conf.cuadros_necesarios} cuadros consecutivos")
    print(f"Politica de paradas: {mision.descripcion()}")
    print(f"Recorrido: {' -> '.join(ruta.secuencia)}")
    if estado_local:
        print(f"Estado local: {estado_local}")
    if args.etiqueta:
        print(f"Sesion: {args.etiqueta}")
    if vista is not None:
        print(f"Vista en vivo: {vista.url()}")
    print("Ctrl+C para salir.\n")

    inicio_iso = datetime.now().astimezone().isoformat(timespec="seconds")

    VENTANA = "Warehouse USAL - escaner QR"
    pantalla_completa = args.pantalla_completa
    if mostrar:
        # WINDOW_NORMAL hace la ventana redimensionable. El defecto de
        # cv2.imshow la clava al tamano del cuadro capturado y no deja
        # tocarla, que es el recuadro chico que aparece si no se hace esto.
        cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
        aw = cfg["captura"].get("ancho") or 640
        ah = cfg["captura"].get("alto") or 480
        cv2.resizeWindow(VENTANA, args.ventana, int(ah * args.ventana / max(aw, 1)))
        if pantalla_completa:
            cv2.setWindowProperty(VENTANA, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        print("Teclas:  f = pantalla completa    + / - = agrandar o achicar    q = salir\n")

    t0 = time.monotonic()
    n_cuadros = 0
    n_eventos = 0
    n_avisos = 0
    ajenos_vistos = set()   # contenidos ajenos distintos
    descartes = 0           # cuantas veces se descarto algo, para el reporte
    fps = 0.0
    ultimo_fps = t0

    try:
        with fuente:
            for cuadro in fuente.cuadros():
                n_cuadros += 1

                lecturas = decod.leer(cuadro)

                # Interpretar y separar lo nuestro de lo ajeno (RF-04)
                validas = {}
                for l in lecturas:
                    try:
                        parada = interpretar(l.contenido)
                    except PayloadInvalido as motivo:
                        # Los ajenos se cuentan por codigo distinto, no por
                        # cuadro: una etiqueta comercial sostenida frente a
                        # la camara son cientos de lecturas del mismo codigo,
                        # y contarlas todas hace parecer que pasa algo raro.
                        # Las paradas ya se deduplican en el Confirmador;
                        # esto le da el mismo trato a lo que se descarta.
                        descartes += 1
                        if l.contenido not in ajenos_vistos:
                            ajenos_vistos.add(l.contenido)
                            texto = l.contenido
                            if len(texto) > 60:
                                texto = texto[:57] + "..."
                            print(f"  .. descartado (no es del proyecto): {texto}")
                            print(f"     motivo: {motivo}")
                        continue
                    validas[parada.clave()] = (parada, l)

                for clave in conf.procesar(list(validas.keys())):
                    parada, lect = validas[clave]

                    # Una parada inactiva se lee y se reporta igual, pero no
                    # entra al recorrido esperado ni cuenta para el minimo.
                    avance = ruta.registrar(parada) if mision.es_activa(parada.id) else None
                    if avance is not None and avance.hay_advertencia:
                        n_avisos += 1

                    evento = construir_evento(
                        id_rover=id_rover,
                        parada=parada,
                        lectura=lect,
                        contenido_crudo=lect.contenido,
                        confianza=conf.cuadros_necesarios,
                        avance=avance,
                        accion=mision.accion(parada),
                        mision=mision.estado(ruta.vuelta),
                    )
                    pub.enviar(evento)
                    n_eventos += 1

                    if estado_local and not escribir_estado_local(estado_local, evento):
                        if not aviso_estado:
                            aviso_estado = True
                            print(f"  !! no se pudo escribir {estado_local}; sigo leyendo sin el")

                ahora = time.monotonic()
                if ahora - ultimo_fps >= 1.0:
                    fps = n_cuadros / (ahora - t0)
                    ultimo_fps = ahora

                quiere_vista = vista is not None and vista.quiere_cuadro()
                if mostrar or quiere_vista:
                    sig = ruta.siguiente_esperada() or "-"
                    m = mision.estado(ruta.vuelta)
                    estado = (f"{fps:.1f} fps | mision {m['cumplidas']}/{m['requeridas']} | "
                              f"sigue: {sig} | ajenos {len(ajenos_vistos)}")
                    marcado = anotar(cuadro, lecturas, estado)
                    if quiere_vista:
                        vista.publicar(marcado)

                if mostrar:
                    cv2.imshow(VENTANA, marcado)
                    tecla = cv2.waitKey(1) & 0xFF
                    if tecla in (ord("q"), 27):
                        break
                    if tecla == ord("f"):
                        pantalla_completa = not pantalla_completa
                        cv2.setWindowProperty(
                            VENTANA, cv2.WND_PROP_FULLSCREEN,
                            cv2.WINDOW_FULLSCREEN if pantalla_completa else cv2.WINDOW_NORMAL)
                    elif tecla in (ord("+"), ord("=")):
                        escalar_ventana(VENTANA, 1.25)
                    elif tecla in (ord("-"), ord("_")):
                        escalar_ventana(VENTANA, 0.8)

    except KeyboardInterrupt:
        pass
    finally:
        if mostrar:
            cv2.destroyAllWindows()
        if vista is not None:
            vista.cerrar()
        pub.cerrar()

    transcurrido = max(time.monotonic() - t0, 0.001)
    faltan = [x for x in ruta.secuencia if x not in ruta.vuelta]
    leidas = len([x for x in ruta.secuencia if x in ruta.vuelta])
    cobertura = leidas / len(ruta.secuencia) * 100 if ruta.secuencia else 0.0

    m_final = mision.estado(ruta.vuelta)

    print("\n--- resumen de la sesion ---")
    print(f"cuadros procesados : {n_cuadros}")
    print(f"fps promedio       : {n_cuadros / transcurrido:.1f}")
    print(f"politica           : {mision.descripcion()}")
    print(f"paradas leidas     : {n_eventos}")
    veredicto = "CUMPLIDA" if m_final["cumplida"] else "pendiente"
    print(f"mision             : {m_final['cumplidas']}/{m_final['requeridas']} ({veredicto})")
    print(f"cobertura          : {leidas}/{len(ruta.secuencia)} paradas activas ({cobertura:.0f}%)")
    print(f"vueltas cerradas   : {ruta.vueltas_completas}")
    estado_vuelta = "completa" if ruta.vuelta_completa else "incompleta"
    print(f"vuelta en curso    : {len(ruta.vuelta)}/{len(ruta.secuencia)} ({estado_vuelta})")
    print(f"con advertencia    : {n_avisos}")
    print(f"codigos ajenos     : {len(ajenos_vistos)} distinto(s), {descartes} descarte(s)")
    print(f"por motor          : {decod.conteo_motor}")
    if faltan:
        print(f"SIN LEER           : {', '.join(faltan)}")

    if args.reporte:
        # Un archivo por sesion permite comparar corridas entre si: misma
        # ruta a distinta velocidad, con y sin iluminacion, etiquetas de
        # 10 y de 15 cm. Sin esto, cada prueba de campo se pierde apenas
        # se cierra la terminal.
        reporte = {
            "etiqueta": args.etiqueta or "",
            "id_rover": id_rover,
            "inicio": inicio_iso,
            "fin": datetime.now().astimezone().isoformat(timespec="seconds"),
            "duracion_s": round(transcurrido, 1),
            "fuente": cfg["captura"].get("tipo"),
            "resolucion": [cfg["captura"].get("ancho"), cfg["captura"].get("alto")],
            "cuadros": n_cuadros,
            "fps_promedio": round(n_cuadros / transcurrido, 1),
            "cuadros_para_confirmar": conf.cuadros_necesarios,
            "paradas_activas": list(mision.activas),
            "minimo_paradas": mision.minimo,
            "paradas_requeridas": m_final["requeridas"],
            "paradas_cumplidas": m_final["cumplidas"],
            "mision_cumplida": m_final["cumplida"],
            "secuencia_esperada": ruta.secuencia,
            "paradas_leidas": list(ruta.vuelta),
            "paradas_sin_leer": faltan,
            "cobertura_pct": round(cobertura, 1),
            "eventos": n_eventos,
            "vueltas_cerradas": ruta.vueltas_completas,
            "vuelta_en_curso_completa": ruta.vuelta_completa,
            "advertencias": n_avisos,
            "codigos_ajenos_distintos": len(ajenos_vistos),
            "descartes_totales": descartes,
            "por_motor": dict(decod.conteo_motor),
        }
        destino = Path(args.reporte)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(reporte, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nreporte guardado: {destino}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
