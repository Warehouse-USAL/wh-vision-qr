"""Una Raspberry Pi fija atendiendo a DOS vehiculos.

Cada vehiculo tiene su camara (por ejemplo un celular con una app de camara
IP) que emite video por la red. Esta Pi lee los dos videos y corre un nodo
completo por cada uno: cada nodo es un cliente MQTT distinto (`camera_<id>`),
asi que para la central son dos camaras independientes.

No cambia nada del programa de siempre: arma dos configs a partir de
config.pi-red-mqtt.json y lanza `python -m vision_qr.main` dos veces.

    python dos_vehiculos.py --broker 192.168.0.13 \\
        --v1 VHC-005 --cam1 http://192.168.0.50:8080/video \\
        --v2 VHC-006 --cam2 http://192.168.0.51:8080/video

El usuario y la clave del broker NO se guardan en ningun archivo (el
repositorio es publico): se toman de MQTT_USER y MQTT_PASS.

    MQTT_USER=... MQTT_PASS=... python dos_vehiculos.py ...

Con --solo-generar solo escribe las configs y muestra que correria.
"""

from __future__ import annotations
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

from vision_qr.payload import HOMES

RAIZ = Path(__file__).resolve().parent


class ArgumentosInvalidos(ValueError):
    pass


def armar_configs(base: dict, vehiculos: list, broker: str | None, puerto: int,
                  destino: Path) -> list:
    """Una config por vehiculo. `vehiculos` es [(id, url_camara, home), ...].

    Devuelve [(id, ruta_del_config, config)]. Cada vehiculo tiene su propio
    estado local y su propio buffer: si compartieran archivo, un nodo pisaria
    lo que escribe el otro.
    """
    ids = [v[0] for v in vehiculos]
    if len(set(ids)) != len(ids):
        raise ArgumentosInvalidos(f"los vehiculos tienen que tener ids distintos: {ids}")
    homes = [v[2] for v in vehiculos if v[2]]
    if len(set(homes)) != len(homes):
        raise ArgumentosInvalidos(f"cada vehiculo necesita un home distinto: {homes}")
    urls = [v[1] for v in vehiculos]
    if len(set(urls)) != len(urls):
        raise ArgumentosInvalidos(
            "los dos vehiculos apuntan a la misma camara: cada uno necesita la suya"
        )

    destino.mkdir(parents=True, exist_ok=True)
    resultado = []
    for vid, url, home in vehiculos:
        if home is not None and home not in HOMES:
            raise ArgumentosInvalidos(f"home {home!r} no existe: usar {', '.join(HOMES)}")
        cfg = json.loads(json.dumps(base))          # copia profunda
        cfg["id_rover"] = vid
        cfg["parada_home"] = home
        cfg["captura"] = {**cfg.get("captura", {}), "tipo": "red", "url": url}
        cfg["estado_local"] = str(destino / f"estado-{vid}.json")
        cfg["publicacion"] = {**cfg.get("publicacion", {"tipo": "mqtt"}),
                              "tipo": "mqtt",
                              "buffer": str(destino / f"pendientes-{vid}.jsonl")}
        mqtt = dict(cfg.get("mqtt", {}))
        mqtt["vehicle_id"] = vid
        if broker:
            mqtt["host"] = broker
        mqtt["port"] = puerto
        mqtt["usuario"] = None      # las credenciales van por entorno, nunca al archivo
        mqtt["clave"] = None
        cfg["mqtt"] = mqtt
        cfg.pop("_notas", None)

        ruta = destino / f"cfg-{vid}.json"
        ruta.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        resultado.append((vid, ruta, cfg))
    return resultado


def _reenviar(proceso: subprocess.Popen, prefijo: str) -> None:
    for linea in proceso.stdout:
        print(f"[{prefijo}] {linea.rstrip()}", flush=True)


def _como_ctrl_c(signum, frame):
    raise KeyboardInterrupt


def lanzar(configs: list, usuario: str | None, clave: str | None) -> int:
    # Ctrl+C y tambien SIGTERM (systemd, kill) cortan los dos nodos en orden.
    # Se instalan los dos a mano: un proceso lanzado en segundo plano desde un
    # script puede heredar SIGINT ignorado y Ctrl+C no haria nada.
    signal.signal(signal.SIGINT, _como_ctrl_c)
    signal.signal(signal.SIGTERM, _como_ctrl_c)
    procesos = []
    hilos = []
    for vid, ruta, _ in configs:
        env = dict(os.environ)
        env["VEHICLE_ID"] = vid            # tiene prioridad sobre el config: que coincida
        env["PYTHONUNBUFFERED"] = "1"
        if usuario:
            env["MQTT_USER"] = usuario
        if clave:
            env["MQTT_PASS"] = clave
        p = subprocess.Popen(
            [sys.executable, "-m", "vision_qr.main", "--config", str(ruta), "--sin-ventana"],
            cwd=RAIZ, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        procesos.append((vid, p))
        h = threading.Thread(target=_reenviar, args=(p, vid), daemon=True)
        h.start()
        hilos.append(h)

    print(f"\n{len(procesos)} vehiculos en marcha. Ctrl+C para cortar los dos.\n", flush=True)
    codigo = 0
    try:
        for vid, p in procesos:
            rc = p.wait()
            if rc not in (0, -2, 130):
                print(f"!! {vid} termino con codigo {rc}", flush=True)
                codigo = 1
    except KeyboardInterrupt:
        print("\nCortando...", flush=True)
        for _, p in procesos:
            p.send_signal(signal.SIGINT)        # salida ordenada: avisa "offline" al broker
        for _, p in procesos:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
    for h in hilos:
        h.join(timeout=1)
    return codigo


def main() -> int:
    ap = argparse.ArgumentParser(description="Una Pi fija, dos vehiculos (dos camaras por red)")
    ap.add_argument("--v1", default="VHC-005", help="Id MQTT del vehiculo 1")
    ap.add_argument("--cam1", required=True, help="URL del video MJPEG del vehiculo 1")
    ap.add_argument("--home1", default="P1", choices=HOMES + ["ninguno"])
    ap.add_argument("--v2", required=True, help="Id MQTT del vehiculo 2")
    ap.add_argument("--cam2", required=True, help="URL del video MJPEG del vehiculo 2")
    ap.add_argument("--home2", default="P2", choices=HOMES + ["ninguno"])
    ap.add_argument("--broker", default=os.environ.get("MQTT_HOST"),
                    help="IP del broker (o MQTT_HOST). Si falta, usa la del config base")
    ap.add_argument("--puerto", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    ap.add_argument("--usuario", default=os.environ.get("MQTT_USER"))
    ap.add_argument("--clave", default=os.environ.get("MQTT_PASS"))
    ap.add_argument("--base", default=str(RAIZ / "config.pi-red-mqtt.json"),
                    help="Config del que se parte")
    ap.add_argument("--destino", default=str(RAIZ / "datos" / "dos_vehiculos"),
                    help="Donde se escriben las configs y el estado de cada vehiculo")
    ap.add_argument("--solo-generar", action="store_true",
                    help="Escribir las configs y salir, sin arrancar los nodos")
    a = ap.parse_args()

    try:
        base = json.loads(Path(a.base).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"No pude leer el config base {a.base}: {e}", file=sys.stderr)
        return 1

    home = lambda h: None if h == "ninguno" else h
    try:
        configs = armar_configs(
            base,
            [(a.v1, a.cam1, home(a.home1)), (a.v2, a.cam2, home(a.home2))],
            a.broker, a.puerto, Path(a.destino),
        )
    except ArgumentosInvalidos as e:
        print(f"Argumentos invalidos: {e}", file=sys.stderr)
        return 1

    host = configs[0][2]["mqtt"].get("host")
    print(f"Broker: {host}:{a.puerto}   usuario: {'si' if a.usuario else 'no (anonimo)'}")
    for vid, ruta, cfg in configs:
        print(f"  {vid}: camara {cfg['captura']['url']}   home {cfg['parada_home']}   config {ruta}")
    if host in (None, "IP_DE_LA_LAPTOP"):
        print("\nFalta el broker: usar --broker IP (el config base trae un marcador).", file=sys.stderr)
        return 1
    if a.solo_generar:
        return 0
    return lanzar(configs, a.usuario, a.clave)


if __name__ == "__main__":
    sys.exit(main())
