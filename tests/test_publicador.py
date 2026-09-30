import json

import pytest

from vision_qr.decodificador import Lectura
from vision_qr.mision import Mision
from vision_qr.payload import construir, interpretar
from vision_qr.publicador import (
    Publicador, PublicadorConBuffer, construir_evento, escribir_estado_local,
)
from vision_qr.recorrido import Recorrido


class Servidor(Publicador):
    """Backend falso: se le puede cortar y devolver la conexion."""
    def __init__(self):
        self.arriba = False
        self.llegaron = []

    def enviar(self, evento):
        if not self.arriba:
            return False
        self.llegaron.append(evento)
        return True


def ev(i):
    return {"id_evento": f"e{i}", "n": i}


class TestBuffer:
    def test_sin_red_nada_se_pierde(self, tmp_path):
        buf = PublicadorConBuffer(Servidor(), str(tmp_path / "p.jsonl"))
        for i in range(1, 4):
            assert buf.enviar(ev(i)) is False
        assert buf.pendientes() == 3

    def test_al_volver_la_red_llega_todo_en_orden(self, tmp_path):
        """Regresion: antes llegaba [4, 1, 2, 3] porque el evento nuevo se
        mandaba antes que la cola. RF-10 pide preservar el orden."""
        srv = Servidor()
        buf = PublicadorConBuffer(srv, str(tmp_path / "p.jsonl"))
        for i in (1, 2, 3):
            buf.enviar(ev(i))
        srv.arriba = True
        buf.enviar(ev(4))
        assert [e["n"] for e in srv.llegaron] == [1, 2, 3, 4]
        assert buf.pendientes() == 0

    def test_los_reenviados_van_marcados_y_el_nuevo_no(self, tmp_path):
        srv = Servidor()
        buf = PublicadorConBuffer(srv, str(tmp_path / "p.jsonl"))
        buf.enviar(ev(1))
        srv.arriba = True
        buf.enviar(ev(2))
        assert srv.llegaron[0]["reenviado"] is True
        assert "reenviado" not in srv.llegaron[1]

    def test_orden_preservado_con_tope_de_drenaje(self, tmp_path):
        srv = Servidor()
        buf = PublicadorConBuffer(srv, str(tmp_path / "p.jsonl"), max_drenaje=2)
        for i in range(1, 6):
            buf.enviar(ev(i))
        srv.arriba = True
        for i in range(6, 12):
            buf.enviar(ev(i))
        orden = [e["n"] for e in srv.llegaron]
        assert orden == sorted(orden)
        assert set(orden) == set(range(1, 12))

    def test_la_cola_sobrevive_a_un_reinicio(self, tmp_path):
        ruta = str(tmp_path / "p.jsonl")
        PublicadorConBuffer(Servidor(), ruta).enviar(ev(1))
        # se apaga el Rover y arranca de nuevo: instancia nueva, mismo archivo
        srv = Servidor(); srv.arriba = True
        buf = PublicadorConBuffer(srv, ruta)
        assert buf.pendientes() == 1
        buf.enviar(ev(2))
        assert [e["n"] for e in srv.llegaron] == [1, 2]

    def test_una_linea_corrupta_no_traba_la_cola(self, tmp_path):
        ruta = tmp_path / "p.jsonl"
        ruta.write_text('{"n": 1, "id_evento": "e1"}\nesto no es json\n{"n": 3, "id_evento": "e3"}\n')
        srv = Servidor(); srv.arriba = True
        buf = PublicadorConBuffer(srv, str(ruta))
        buf.enviar(ev(4))
        assert [e["n"] for e in srv.llegaron] == [1, 3, 4]
        assert buf.pendientes() == 0


class TestEvento:
    def armar(self, **extra):
        parada = interpretar(construir("PA2"))
        lectura = Lectura("WH2|PA2", [(0, 0), (10, 0), (10, 10), (0, 10)], "zbar")
        return construir_evento("rover-01", parada, lectura, "WH2|PA2", 3, **extra)

    def test_campos_del_contrato(self):
        e = self.armar()
        for campo in ("id_evento", "id_rover", "marca_temporal", "tipo",
                      "contenido_crudo", "parada", "confianza", "reenviado"):
            assert campo in e
        assert e["tipo"] == "llegada_parada"
        assert e["parada"]["id"] == "PA2"
        assert e["reenviado"] is False

    def test_id_de_evento_unico(self):
        assert self.armar()["id_evento"] != self.armar()["id_evento"]

    def test_incluye_accion_y_mision_cuando_se_piden(self):
        m = Mision(["PA2", "PM1"])
        p = interpretar(construir("PA2"))
        e = self.armar(accion=m.accion(p), mision=m.estado(["PA2"]))
        assert e["accion"] == "detener"
        assert e["mision"] == {"activas": ["PA2", "PM1"], "requeridas": 2,
                               "cumplidas": 1, "cumplida": False}

    def test_una_parada_inactiva_va_sin_bloque_de_avance(self):
        assert "avance" not in self.armar()

    def test_incluye_avance_si_hay(self):
        r = Recorrido()
        e = self.armar(avance=r.registrar(interpretar(construir("PA2"))))
        assert e["avance"]["salteadas"] == ["PA1"]


class TestEstadoLocal:
    def evento(self):
        p = interpretar(construir("PM1"))
        m = Mision()
        return construir_evento("rover-01", p, None, "WH2|PM1", 3,
                                accion=m.accion(p), mision=m.estado(["PM1"]))

    def test_deja_la_ultima_parada(self, tmp_path):
        ruta = tmp_path / "datos" / "estado.json"       # la carpeta no existe todavia
        assert escribir_estado_local(str(ruta), self.evento()) is True
        estado = json.loads(ruta.read_text(encoding="utf-8"))
        assert estado["parada"]["id"] == "PM1"
        assert estado["accion"] == "esperar_operador"

    def test_reescribe_sin_dejar_temporales(self, tmp_path):
        ruta = tmp_path / "estado.json"
        for _ in range(3):
            escribir_estado_local(str(ruta), self.evento())
        assert [p.name for p in tmp_path.iterdir()] == ["estado.json"]

    def test_un_fallo_no_levanta_excepcion(self, tmp_path):
        # el destino es una carpeta: no se puede reemplazar por un archivo
        (tmp_path / "estado.json").mkdir()
        assert escribir_estado_local(str(tmp_path / "estado.json"), self.evento()) is False
