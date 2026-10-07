"""Nodo MQTT, con un cliente falso: no hace falta broker para probar la logica.

Fijan el protocolo del equipo de Comunicacion (topics y formato de los
mensajes) y las dos decisiones de diseño que importan: nunca encolar un
qr_detected sin conexion, y reiniciar la racha cuando cambia el objetivo.
"""

import json
from types import SimpleNamespace

import pytest

from vision_qr.nodo_mqtt import NodoMqtt
from vision_qr.publicador import PublicadorMqtt, construir_publicador


class ClienteFalso:
    def __init__(self):
        self.publicados = []
        self.suscripciones = []
        self.voluntad = None

    def username_pw_set(self, u, p): self.credenciales = (u, p)
    def will_set(self, topic, payload, qos=0): self.voluntad = (topic, json.loads(payload), qos)
    def reconnect_delay_set(self, **kw): pass
    def connect_async(self, host, port, keepalive): self.destino = (host, port)
    def loop_start(self): pass
    def loop_stop(self): pass
    def disconnect(self): pass
    def subscribe(self, lista): self.suscripciones.extend(lista)

    def publish(self, topic, payload, qos=0):
        self.publicados.append((topic, json.loads(payload), qos))
        return SimpleNamespace(rc=0, wait_for_publish=lambda t=None: None)


def nodo(cuadros=1, conectado=True, **kw):
    c = ClienteFalso()
    n = NodoMqtt("VHC-001", "127.0.0.1", cliente=c, cuadros_objetivo=cuadros, avisar=lambda m: None, **kw)
    if conectado:
        n._al_conectar(c, None, None, 0)
    return n, c


def mensaje(topic, datos):
    return SimpleNamespace(topic=topic, payload=json.dumps(datos).encode())


def poner_objetivo(n, c, qr="WH2|PA1", leg="L1"):
    n._al_recibir(c, None, mensaje(n.topic_cmd, {"cmd": "set_target", "qr": qr, "leg_id": leg}))


def eventos(c):
    return [p for t, p, _ in c.publicados if t.endswith("/camera/event")]


def test_topics_y_ultima_voluntad_como_el_nodo_original():
    n, c = nodo(conectado=False)
    assert n.topic_cmd == "devices/VHC-001/camera/cmd"
    assert n.topic_evento == "devices/VHC-001/camera/event"
    assert n.topic_estado == "devices/VHC-001/camera/status"
    assert n.topic_telemetria == "devices/VHC-001/camera/telemetry"
    assert c.voluntad == ("devices/VHC-001/camera/status", {"online": False}, 1)


def test_al_conectar_se_suscribe_y_anuncia_online():
    n, c = nodo()
    assert (n.topic_cmd, 1) in c.suscripciones
    assert ("devices/broadcast/telemetry_request", 0) in c.suscripciones
    assert ("central/status", 1) in c.suscripciones
    assert ("devices/VHC-001/camera/status", {"online": True}, 1) in c.publicados


def test_sin_objetivo_no_avisa_nada():
    n, c = nodo()
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is False
    assert eventos(c) == []


def test_avisa_cuando_ve_el_objetivo_y_lo_descarta():
    n, c = nodo()
    poner_objetivo(n, c)
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is True
    ev = eventos(c)
    assert len(ev) == 1
    assert ev[0]["event"] == "qr_detected" and ev[0]["qr"] == "WH2|PA1" and ev[0]["leg_id"] == "L1"
    assert isinstance(ev[0]["timestamp"], float)
    assert n.objetivo() is None                     # one-shot
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is False
    assert len(eventos(c)) == 1


def test_ignora_otras_etiquetas():
    n, c = nodo()
    poner_objetivo(n, c, "WH2|PM2")
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is False
    assert n.objetivo() is not None


def test_el_objetivo_puede_ser_el_id_de_la_parada_o_un_texto_ajeno():
    n, c = nodo()
    poner_objetivo(n, c, "PA2")
    assert n.procesar_cuadro(["WH2|PA2"], ["PA2"]) is True
    poner_objetivo(n, c, "Z1-L3-P07")                # un QR que no es nuestro
    assert n.procesar_cuadro(["Z1-L3-P07"], []) is True


def test_exige_cuadros_consecutivos_si_se_configura():
    n, c = nodo(cuadros=3)
    poner_objetivo(n, c)
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is False
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is False
    assert n.procesar_cuadro([], []) is False        # se corta la racha
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is False
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is False
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is True


def test_un_objetivo_nuevo_reinicia_la_racha():
    n, c = nodo(cuadros=2)
    poner_objetivo(n, c, "WH2|PA1")
    n.procesar_cuadro(["WH2|PA1"], ["PA1"])
    poner_objetivo(n, c, "WH2|PA1", leg="L2")        # mismo QR, objetivo nuevo
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is False


def test_sin_conexion_no_se_publica_y_se_conserva_el_objetivo():
    """Un qr_detected tardio frenaria al Rover donde ya no esta."""
    n, c = nodo()
    poner_objetivo(n, c)
    n._al_desconectar()
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is False
    assert eventos(c) == [] and n.objetivo() is not None
    n._al_conectar(c, None, None, 0)
    assert n.procesar_cuadro(["WH2|PA1"], ["PA1"]) is True


def test_clear_target_y_central_offline_descartan_el_objetivo():
    n, c = nodo()
    poner_objetivo(n, c)
    n._al_recibir(c, None, mensaje(n.topic_cmd, {"cmd": "clear_target"}))
    assert n.objetivo() is None
    poner_objetivo(n, c)
    n._al_recibir(c, None, mensaje("central/status", {"online": False}))
    assert n.objetivo() is None
    poner_objetivo(n, c)
    n._al_recibir(c, None, mensaje("central/status", {"online": True}))
    assert n.objetivo() is not None


def test_set_target_sin_qr_se_ignora():
    n, c = nodo()
    n._al_recibir(c, None, mensaje(n.topic_cmd, {"cmd": "set_target"}))
    assert n.objetivo() is None


def test_telemetria_tiene_los_campos_del_nodo_original():
    n, c = nodo()
    n.procesar_cuadro([], [])
    n.fps = 29.46
    poner_objetivo(n, c, "WH2|PA3")
    n._al_recibir(c, None, mensaje("devices/broadcast/telemetry_request", {}))
    t = [p for topic, p, _ in c.publicados if topic.endswith("/telemetry")][-1]
    assert set(t) == {"vehicle_id", "camera_ok", "fps", "searching_qr", "detections", "cpu_temp", "uptime_s"}
    assert t["vehicle_id"] == "VHC-001" and t["camera_ok"] is True
    assert t["fps"] == 29.5 and t["searching_qr"] == "WH2|PA3"


def test_mensaje_corrupto_no_tira_el_nodo():
    n, c = nodo()
    n._al_recibir(c, None, SimpleNamespace(topic=n.topic_cmd, payload=b"{no es json"))
    n._al_recibir(c, None, SimpleNamespace(topic=n.topic_cmd, payload=b"[1, 2]"))


def test_publica_la_parada_completa_por_el_topic_propio():
    n, c = nodo()
    pub = construir_publicador({"tipo": "mqtt"}, nodo=n)
    assert isinstance(pub, PublicadorMqtt)
    assert pub.enviar({"parada": {"id": "PA1"}, "accion": "detener"}) is True
    assert c.publicados[-1][0] == "devices/VHC-001/camera/stop_event"


def test_la_parada_sin_conexion_va_al_buffer(tmp_path):
    n, c = nodo(conectado=False)
    pub = construir_publicador({"tipo": "mqtt", "buffer": str(tmp_path / "pend.jsonl")}, nodo=n)
    assert pub.enviar({"id_evento": "e1", "parada": {"id": "PA1", "tipo": "automatica", "orden": 1},
                       "accion": "detener"}) is False
    assert pub.pendientes() == 1


def test_transporte_mqtt_sin_seccion_mqtt_da_error_claro():
    with pytest.raises(ValueError, match="mqtt"):
        construir_publicador({"tipo": "mqtt"})


def test_el_entorno_gana_sobre_el_config():
    cfg = {"host": "10.0.0.1", "port": 1883, "vehicle_id": "A", "usuario": "u"}
    env = {"VEHICLE_ID": "VHC-007", "MQTT_HOST": "192.168.0.10", "MQTT_PORT": "1884",
           "MQTT_USER": "admin_admin", "MQTT_PASS": "x"}
    n = NodoMqtt.desde_config(cfg, "rover-01", env=env, cliente=ClienteFalso())
    assert (n.vehicle_id, n.host, n.port) == ("VHC-007", "192.168.0.10", 1884)
    sin_env = NodoMqtt.desde_config(cfg, "rover-01", env={}, cliente=ClienteFalso())
    assert (sin_env.vehicle_id, sin_env.host) == ("A", "10.0.0.1")
    solo_id = NodoMqtt.desde_config({}, "rover-01", env={}, cliente=ClienteFalso())
    assert solo_id.vehicle_id == "rover-01"
