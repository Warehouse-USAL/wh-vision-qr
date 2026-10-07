"""Central simulada: le pide QR al nodo y mide cuanto tarda en avisar.

Hace lo que hara la central real: manda set_target, espera el qr_detected y
pasa al siguiente. Sirve para probar el nodo (Pi o laptop) sin depender de que
la central este lista.

Uso:
    python central_simulada.py --qr WH2|PA1 WH2|PM2
    python central_simulada.py --qr WH2|PA1 --vehiculo VHC-001 --host 192.168.1.50
    python central_simulada.py --qr Z1-L3-P07 --espera 60
    python central_simulada.py --solo-escuchar            # no pide nada: mira todo lo que publica el nodo

Mostrarle a la camara cada QR pedido; el tiempo que imprime es desde el pedido
hasta el aviso, asi que incluye lo que tardes en mostrarlo.
"""

import argparse
import json
import os
import sys
import threading
import time


def main() -> int:
    ap = argparse.ArgumentParser(description="Central simulada del nodo MQTT")
    ap.add_argument("--qr", nargs="*", default=[], help="Los QR a pedir, en orden")
    ap.add_argument("--vehiculo", default=os.environ.get("VEHICLE_ID", "VHC-001"))
    ap.add_argument("--host", default=os.environ.get("MQTT_HOST", "127.0.0.1"))
    ap.add_argument("--puerto", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    ap.add_argument("--usuario", default=os.environ.get("MQTT_USER"))
    ap.add_argument("--clave", default=os.environ.get("MQTT_PASS"))
    ap.add_argument("--espera", type=float, default=30.0, help="Segundos maximos por cada QR")
    ap.add_argument("--solo-escuchar", action="store_true")
    args = ap.parse_args()
    if not args.qr and not args.solo_escuchar:
        sys.exit("Indicar --qr ... o --solo-escuchar")

    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        sys.exit("Falta paho-mqtt. Instalalo con: pip install paho-mqtt")

    base = f"devices/{args.vehiculo}/camera"
    detectado = threading.Event()
    ultimo = {}

    def al_conectar(c, u, f, rc, *a):
        c.subscribe(f"{base}/#", 1)
        c.publish("central/status", json.dumps({"online": True}), qos=1)

    def al_recibir(c, u, m):
        try:
            datos = json.loads(m.payload.decode())
        except Exception:
            return
        nombre = m.topic.rsplit("/", 1)[-1]
        if nombre == "cmd":
            return
        print(f"  <- {nombre:10s} {json.dumps(datos, ensure_ascii=False)}")
        if nombre == "event" and datos.get("event") == "qr_detected":
            ultimo.update(datos)
            detectado.set()

    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="central_simulada")
    except AttributeError:
        c = mqtt.Client(client_id="central_simulada")
    if args.usuario:
        c.username_pw_set(args.usuario, args.clave)
    c.on_connect, c.on_message = al_conectar, al_recibir
    c.will_set("central/status", json.dumps({"online": False}), qos=1)
    try:
        c.connect(args.host, args.puerto, keepalive=10)
    except OSError as e:
        sys.exit(f"No se pudo conectar al broker {args.host}:{args.puerto}: {e}")
    c.loop_start()
    time.sleep(1.0)

    try:
        if args.solo_escuchar:
            print("Escuchando. Ctrl+C para cortar.")
            while True:
                time.sleep(1)
        ok = 0
        for i, qr in enumerate(args.qr, 1):
            detectado.clear()
            print(f"\n[{i}/{len(args.qr)}] pidiendo '{qr}'. Mostralo a la camara...")
            t0 = time.monotonic()
            c.publish(f"{base}/cmd", json.dumps({"cmd": "set_target", "qr": qr, "leg_id": f"L{i}"}), qos=1)
            if detectado.wait(args.espera):
                ok += 1
                print(f"  OK en {time.monotonic() - t0:.1f} s (leg_id={ultimo.get('leg_id')})")
            else:
                print(f"  SIN RESPUESTA en {args.espera:.0f} s")
                c.publish(f"{base}/cmd", json.dumps({"cmd": "clear_target"}), qos=1)
        c.publish("devices/broadcast/telemetry_request", "{}")
        time.sleep(1.0)
        print(f"\n{ok}/{len(args.qr)} QR detectados.")
        return 0 if ok == len(args.qr) else 1
    except KeyboardInterrupt:
        return 0
    finally:
        c.publish("central/status", json.dumps({"online": False}), qos=1).wait_for_publish(1)
        c.loop_stop()


if __name__ == "__main__":
    raise SystemExit(main())
