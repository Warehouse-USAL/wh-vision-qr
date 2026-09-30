"""Servidor de prueba que simula el Backend (para QR-20 y QR-21).

Permite probar la publicacion y el buffer offline sin depender de que el
grupo de Backend tenga su endpoint listo. Es deliberadamente tonto: solo
recibe, valida lo minimo e imprime.

Uso:
    python servidor_prueba.py
    python servidor_prueba.py --puerto 8000 --fallar     # simula caida

Con --fallar responde error a todo, para verificar que el Rover encola
en lugar de perder eventos. Apagalo y prendelo con Ctrl+C para ver el
reenvio en accion.
"""

from __future__ import annotations
import argparse
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

RECIBIDOS: dict[str, dict] = {}
FALLAR = False

CAMPOS_OBLIGATORIOS = ["id_evento", "id_rover", "marca_temporal", "tipo",
                       "contenido_crudo", "parada", "reenviado"]


class Manejador(BaseHTTPRequestHandler):
    def _responder(self, codigo: int, cuerpo: dict):
        datos = json.dumps(cuerpo).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_POST(self):
        if FALLAR:
            self._responder(503, {"error": "backend simulado caido"})
            print("  xx rechazado (modo --fallar)")
            return

        largo = int(self.headers.get("Content-Length", 0))
        try:
            evento = json.loads(self.rfile.read(largo))
        except json.JSONDecodeError:
            self._responder(400, {"error": "json invalido"})
            return

        faltan = [c for c in CAMPOS_OBLIGATORIOS if c not in evento]
        if faltan:
            self._responder(422, {"error": "faltan campos", "campos": faltan})
            print(f"  xx evento rechazado, faltan: {faltan}")
            return

        # Deduplicacion por id_evento (QR-22): asi se comporta un Backend
        # correcto ante un reenvio desde el buffer del Rover.
        eid = evento["id_evento"]
        if eid in RECIBIDOS:
            self._responder(200, {"estado": "duplicado_ignorado"})
            print(f"  == duplicado ignorado {eid[:8]}")
            return

        RECIBIDOS[eid] = evento
        p = evento["parada"]
        marca = "REENVIADO" if evento.get("reenviado") else "en vivo  "
        tipo = "auto " if p["tipo"] == "automatica" else "manual"
        hora = datetime.now().strftime("%H:%M:%S")
        aviso = ""
        av = evento.get("avance")
        if av and av.get("salteadas"):
            aviso = "  (!) sin leer: " + ", ".join(av["salteadas"])
        print(f"  {hora}  [{marca}]  {p['id']}  {tipo}  "
              f"total: {len(RECIBIDOS)}{aviso}")
        self._responder(201, {"estado": "ok", "total": len(RECIBIDOS)})

    def do_GET(self):
        self._responder(200, {
            "eventos": len(RECIBIDOS),
            "paradas_vistas": sorted({e["parada"]["id"] for e in RECIBIDOS.values()}),
        })

    def log_message(self, *a):
        pass  # silenciar el log por defecto, ya imprimimos lo util


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8000)
    ap.add_argument("--fallar", action="store_true",
                    help="Responder error a todo, para probar el buffer offline")
    args = ap.parse_args()

    global FALLAR
    FALLAR = args.fallar

    srv = HTTPServer(("0.0.0.0", args.puerto), Manejador)
    print(f"Backend simulado en http://localhost:{args.puerto}/eventos")
    if FALLAR:
        print("MODO FALLA: se rechaza todo. El Rover deberia encolar sin perder nada.")
    print("Ctrl+C para detener.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print(f"\nTotal recibido: {len(RECIBIDOS)} evento(s) unico(s)")


if __name__ == "__main__":
    main()
