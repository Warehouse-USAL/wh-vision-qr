#!/usr/bin/env bash
# Levanta el nodo QR en la Raspberry Pi con un solo comando.
#
#   ./iniciar_pi.sh [VEHICULO] [BROKER] [HOME]
#
# Por defecto: VHC-000, broker 192.168.0.11, home P1, camara CSI (picamera).
#
#   ./iniciar_pi.sh                         # todo por defecto
#   ./iniciar_pi.sh VHC-005 192.168.0.11 P2
#
# Con una camara por red (por ejemplo la webcam de la laptop con
# transmitir_camara.py), en vez de la CSI:
#
#   CAMARA_URL=http://IP_LAPTOP:8080/video ./iniciar_pi.sh
#
# El usuario y la clave del broker NO estan en el repo (es publico): se toman
# de MQTT_USER y MQTT_PASS, y si faltan el script los pide.
#
#   DRY=1 ./iniciar_pi.sh        # solo arma el config y lo muestra, sin arrancar
set -euo pipefail
cd "$(dirname "$0")"

VEHICULO="${1:-VHC-000}"
BROKER="${2:-192.168.0.11}"
HOME_P="${3:-P1}"
CAMARA_URL="${CAMARA_URL:-}"
PUERTO="${MQTT_PORT:-1883}"

if [ -f .env/bin/activate ]; then
    # shellcheck disable=SC1091
    source .env/bin/activate
fi
PY="${PYTHON:-python}"

CFG="$(mktemp /tmp/cfg-nodo-XXXXXX.json)"
trap 'rm -f "$CFG"' EXIT

if [ -n "$CAMARA_URL" ]; then BASE=config.pi-red-mqtt.json; else BASE=config.pi-mqtt.json; fi

"$PY" - "$BASE" "$CFG" "$VEHICULO" "$BROKER" "$HOME_P" "$CAMARA_URL" "$PUERTO" <<'PYEOF'
import json, sys
base, destino, vehiculo, broker, home, url, puerto = sys.argv[1:8]
c = json.load(open(base, encoding="utf-8"))
c["id_rover"] = vehiculo
c["parada_home"] = home
c["mqtt"]["host"] = broker
c["mqtt"]["port"] = int(puerto)
c["mqtt"]["vehicle_id"] = vehiculo
c["mqtt"]["usuario"] = None   # las credenciales van por entorno, nunca a un archivo
c["mqtt"]["clave"] = None
if url:
    c["captura"] = {**c.get("captura", {}), "tipo": "red", "url": url}
else:
    c["captura"] = {"tipo": "picamera", "ancho": 320, "alto": 240}
json.dump(c, open(destino, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
PYEOF

echo "Vehiculo: $VEHICULO   broker: $BROKER:$PUERTO   home: $HOME_P"
if [ -n "$CAMARA_URL" ]; then
    echo "Camara:   por red ($CAMARA_URL)"
else
    echo "Camara:   CSI (picamera) 320x240"
fi

if [ "${DRY:-0}" = "1" ]; then
    echo "--- config generado (DRY=1, no se arranca nada) ---"
    cat "$CFG"
    exit 0
fi

# Credenciales: del entorno, y si faltan, se piden.
if [ -z "${MQTT_USER:-}" ]; then read -r -p "Usuario del broker: " MQTT_USER; fi
if [ -z "${MQTT_PASS:-}" ]; then read -r -s -p "Clave del broker: " MQTT_PASS; echo; fi
export MQTT_USER MQTT_PASS

# Chequeos previos: avisan claro en vez de dejar un traceback.
if ! "$PY" -c "import socket,sys;socket.create_connection((sys.argv[1],int(sys.argv[2])),3)" "$BROKER" "$PUERTO" 2>/dev/null; then
    echo "!! No llego al broker $BROKER:$PUERTO. Revisar IP con Comunicacion y que la Pi este en la misma red." >&2
    exit 1
fi
if [ -z "$CAMARA_URL" ]; then
    if ! rpicam-hello --list-cameras 2>&1 | grep -q "imx219\|Available cameras"; then
        echo "!! La Pi no detecta la camara CSI (rpicam-hello --list-cameras). Revisar la cinta con la Pi apagada." >&2
        exit 1
    fi
fi

echo "Vista en vivo: http://$(hostname -I | awk '{print $1}'):8080/"
"$PY" -m vision_qr.main --config "$CFG" --sin-ventana --vista-web
