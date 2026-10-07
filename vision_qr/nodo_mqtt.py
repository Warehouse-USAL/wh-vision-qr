"""Nodo MQTT: conecta el modulo de vision con la central del Rover.

Implementa el protocolo que definio el equipo de Comunicacion en su
`rpi_camara/camara.py`, para que la Pi hable con la central igual que ellos
esperan, pero con la lectura de este modulo (validacion de etiquetas,
politica de paradas) por debajo.

La central le dice a la camara que QR buscar y la camara avisa cuando lo ve:

    devices/<vehiculo>/camera/cmd        <- central. {"cmd": "set_target", "qr": "WH2|PA1", "leg_id": ...}
                                                     {"cmd": "clear_target"}  {"cmd": "telemetry_request"}
    devices/<vehiculo>/camera/event      -> central. {"event": "qr_detected", "qr", "leg_id", "timestamp"}
    devices/<vehiculo>/camera/status     -> central. {"online": true|false}   (false = ultima voluntad)
    devices/<vehiculo>/camera/telemetry  -> central. fps, camera_ok, searching_qr, detections, cpu_temp, uptime_s
    devices/broadcast/telemetry_request  <- central. Pide telemetria a todos
    central/status                       <- central. {"online": false} descarta el objetivo

Ademas, y aparte de ese protocolo, cada parada confirmada sale por
`devices/<vehiculo>/camera/stop_event` con el evento completo de este modulo
(accion, mision, avance...). Es un agregado nuestro, a confirmar con
Comunicacion; el protocolo de ellos no se toca.

Decisiones que conviene no revertir sin discutirlas:

  * Un qr_detected NUNCA se encola sin conexion. Si se guardara y se enviara al
    volver la red, la central frenaria al Rover en un lugar que ya paso. Sin
    enlace no se publica y el objetivo se conserva.

  * El objetivo se compara contra el texto decodificado (o el id de la parada,
    ej. "PA1"), sin exigir el prefijo WH2: la central puede pedir cualquier QR.
    Con 1 cuadro alcanza, como en el nodo original: un texto que coincide
    exactamente con el pedido no se obtiene por error de lectura, y cada cuadro
    extra es latencia antes de frenar.

  * Las credenciales NO van en el config. Se leen de MQTT_USER / MQTT_PASS, los
    mismos nombres que usa el nodo original.
"""

from __future__ import annotations
import json
import os
import threading
import time
from typing import Callable, Iterable, Optional

TOPIC_TELEMETRIA_GENERAL = "devices/broadcast/telemetry_request"
TOPIC_CENTRAL = "central/status"


def _crear_cliente(client_id: str):
    import paho.mqtt.client as mqtt
    try:   # paho-mqtt 2.x
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)
    except AttributeError:   # paho-mqtt 1.x
        return mqtt.Client(client_id=client_id, clean_session=True)


def _temperatura_cpu() -> Optional[float]:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read()) / 1000, 1)
    except Exception:
        return None


class NodoMqtt:
    def __init__(self, vehicle_id: str, host: str, port: int = 1883,
                 usuario: Optional[str] = None, clave: Optional[str] = None,
                 cuadros_objetivo: int = 1, cliente=None,
                 avisar: Callable[[str], None] = print):
        self.vehicle_id = vehicle_id
        self.host = host
        self.port = int(port)
        self.cuadros_objetivo = max(int(cuadros_objetivo), 1)
        self._avisar = avisar

        base = f"devices/{vehicle_id}/camera"
        self.topic_cmd = f"{base}/cmd"
        self.topic_evento = f"{base}/event"
        self.topic_estado = f"{base}/status"
        self.topic_telemetria = f"{base}/telemetry"
        self.topic_parada = f"{base}/stop_event"

        self._lock = threading.Lock()
        self._objetivo: Optional[dict] = None
        self._conectado = False
        self._racha = 0
        self._racha_de = None
        self._ultimo_cuadro = 0.0
        self.fps = 0.0
        self.detecciones = 0
        self._inicio = time.time()

        self._cliente = cliente if cliente is not None else _crear_cliente(f"camera_{vehicle_id}")
        if usuario:
            self._cliente.username_pw_set(usuario, clave)
        self._cliente.will_set(self.topic_estado, json.dumps({"online": False}), qos=1)
        self._cliente.reconnect_delay_set(min_delay=1, max_delay=10)
        self._cliente.on_connect = self._al_conectar
        self._cliente.on_disconnect = self._al_desconectar
        self._cliente.on_message = self._al_recibir

    @classmethod
    def desde_config(cls, cfg: dict, id_rover: str, env=None, **extra) -> "NodoMqtt":
        """Arma el nodo desde la seccion "mqtt" del config. Las variables de
        entorno ganan sobre el archivo: asi el mismo config sirve en cada
        vehiculo y el servicio de systemd solo cambia VEHICLE_ID."""
        env = os.environ if env is None else env
        return cls(
            vehicle_id=env.get("VEHICLE_ID") or cfg.get("vehicle_id") or id_rover,
            host=env.get("MQTT_HOST") or cfg.get("host", "127.0.0.1"),
            port=int(env.get("MQTT_PORT") or cfg.get("port", 1883)),
            usuario=env.get("MQTT_USER") or cfg.get("usuario"),
            clave=env.get("MQTT_PASS") or cfg.get("clave"),
            cuadros_objetivo=cfg.get("cuadros_para_confirmar_objetivo", 1),
            **extra,
        )

    # --- ciclo de vida --------------------------------------------------------

    def iniciar(self) -> None:
        self._cliente.connect_async(self.host, self.port, keepalive=10)
        self._cliente.loop_start()

    def cerrar(self) -> None:
        try:
            self._cliente.publish(self.topic_estado, json.dumps({"online": False}), qos=1).wait_for_publish(2)
        except Exception:
            pass
        self._cliente.loop_stop()
        try:
            self._cliente.disconnect()
        except Exception:
            pass

    @property
    def conectado(self) -> bool:
        return self._conectado

    # --- callbacks de paho (compatibles con paho 1.x y 2.x) ---------------------

    def _al_conectar(self, cliente, userdata, flags, rc, *args):
        fallo = rc.is_failure if hasattr(rc, "is_failure") else rc != 0
        if fallo:
            self._avisar(f"  !! MQTT: conexion rechazada ({rc})")
            return
        self._conectado = True
        self._avisar(f"  ++ MQTT conectado a {self.host}:{self.port} como {self.vehicle_id}")
        cliente.subscribe([(self.topic_cmd, 1), (TOPIC_TELEMETRIA_GENERAL, 0), (TOPIC_CENTRAL, 1)])
        cliente.publish(self.topic_estado, json.dumps({"online": True}), qos=1)

    def _al_desconectar(self, *args):
        self._conectado = False
        self._avisar("  .. MQTT desconectado, reintentando")

    def _al_recibir(self, cliente, userdata, msg):
        try:
            datos = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            self._avisar(f"  .. MQTT: mensaje invalido en {msg.topic}")
            return
        if not isinstance(datos, dict):
            return
        if msg.topic == TOPIC_TELEMETRIA_GENERAL:
            self.enviar_telemetria()
        elif msg.topic == TOPIC_CENTRAL:
            if not datos.get("online", False):
                self._avisar("  .. MQTT: la central esta offline, se descarta el objetivo")
                self._poner_objetivo(None)
        elif msg.topic == self.topic_cmd:
            self._ejecutar_comando(datos)

    def _ejecutar_comando(self, datos: dict) -> None:
        cmd = datos.get("cmd")
        if cmd == "set_target":
            qr = str(datos.get("qr", "")).strip()
            if not qr:
                self._avisar("  .. MQTT: set_target sin 'qr', se ignora")
                return
            self._poner_objetivo({"qr": qr, "leg_id": datos.get("leg_id")})
            self._avisar(f"  >> buscando QR '{qr}'")
        elif cmd == "clear_target":
            self._poner_objetivo(None)
            self._avisar("  >> objetivo descartado")
        elif cmd == "telemetry_request":
            self.enviar_telemetria()

    # --- objetivo -----------------------------------------------------------------

    def _poner_objetivo(self, valor: Optional[dict]) -> None:
        with self._lock:
            self._objetivo = valor

    def objetivo(self) -> Optional[dict]:
        with self._lock:
            return self._objetivo

    def procesar_cuadro(self, textos: Iterable[str], ids_parada: Iterable[str] = ()) -> bool:
        """Se llama una vez por cuadro. Devuelve True si en este cuadro se
        publico el qr_detected del objetivo vigente."""
        self._ultimo_cuadro = time.monotonic()
        objetivo = self.objetivo()
        if objetivo is None:
            self._racha, self._racha_de = 0, None
            return False
        if self._racha_de is not objetivo:     # llego un objetivo nuevo: empezar de cero
            self._racha, self._racha_de = 0, objetivo

        visto = objetivo["qr"] in {t.strip() for t in textos} or objetivo["qr"] in set(ids_parada)
        self._racha = self._racha + 1 if visto else 0
        if self._racha < self.cuadros_objetivo:
            return False
        return self._publicar_deteccion(objetivo)

    def _publicar_deteccion(self, objetivo: dict) -> bool:
        if not self._conectado:
            return False       # nunca encolar: ver la nota del modulo
        info = self._cliente.publish(self.topic_evento, json.dumps({
            "event": "qr_detected",
            "qr": objetivo["qr"],
            "leg_id": objetivo["leg_id"],
            "timestamp": time.time(),
        }), qos=1)
        if getattr(info, "rc", 0) != 0:
            return False
        with self._lock:
            if self._objetivo is objetivo:
                self._objetivo = None
        self._racha, self._racha_de = 0, None
        self.detecciones += 1
        self._avisar(f"  >> QR '{objetivo['qr']}' detectado: avisado a la central")
        return True

    # --- salidas ----------------------------------------------------------------------

    def publicar_parada(self, evento: dict) -> bool:
        """Evento completo de este modulo. Lo usa PublicadorMqtt, que a su vez
        lo envuelve el buffer en disco: si devuelve False, el evento no se pierde."""
        if not self._conectado:
            return False
        info = self._cliente.publish(self.topic_parada, json.dumps(evento, ensure_ascii=False), qos=1)
        return getattr(info, "rc", 0) == 0

    def enviar_telemetria(self) -> None:
        objetivo = self.objetivo()
        self._cliente.publish(self.topic_telemetria, json.dumps({
            "vehicle_id": self.vehicle_id,
            "camera_ok": (time.monotonic() - self._ultimo_cuadro) < 2.0 if self._ultimo_cuadro else False,
            "fps": round(self.fps, 1),
            "searching_qr": objetivo["qr"] if objetivo else None,
            "detections": self.detecciones,
            "cpu_temp": _temperatura_cpu(),
            "uptime_s": int(time.time() - self._inicio),
        }), qos=0)
