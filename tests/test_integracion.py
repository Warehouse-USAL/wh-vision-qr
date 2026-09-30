"""Pruebas de punta a punta: se corre el programa de verdad, con imagenes en
lugar de camara, y se mira lo que imprime y lo que escribe.

Es lo mas cercano a probar con el Rover que se puede hacer sin Rover.
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyzbar.pyzbar")
qrcode = pytest.importorskip("qrcode")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import generar_etiquetas  # noqa: E402


@pytest.fixture
def etiquetas(tmp_path):
    destino = tmp_path / "etiquetas"
    generar_etiquetas.generar(["PA1", "PA2", "PA3", "PM1", "PM2", "PM3"], 100, destino)
    return destino


def correr(tmp_path, config, *extra):
    """Ejecuta el modulo como lo haria un usuario y devuelve el resultado."""
    base = {
        "id_rover": "rover-test", "mostrar_ventana": False, "cuadros_para_confirmar": 2,
        "publicacion": {"tipo": "consola"},
        "captura": {"tipo": "archivos", "patron": str(tmp_path / "etiquetas" / "P*.png"),
                    "repeticiones": 3},
    }
    base.update(config)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(base), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "vision_qr.main", "--config", str(cfg), *extra],
        cwd=RAIZ, capture_output=True, text=True, timeout=120,
    )


def test_recorrido_completo(tmp_path, etiquetas):
    r = correr(tmp_path, {})
    assert r.returncode == 0, r.stderr
    assert "mision             : 6/6 (CUMPLIDA)" in r.stdout
    assert "cobertura          : 6/6" in r.stdout
    assert "SIN LEER" not in r.stdout


def test_paradas_especificas(tmp_path, etiquetas):
    r = correr(tmp_path, {"paradas_activas": ["PA1", "PM2"]})
    assert r.returncode == 0, r.stderr
    assert "Politica de paradas: solo PA1, PM2" in r.stdout
    assert "mision             : 2/2 (CUMPLIDA)" in r.stdout
    # las inactivas se leen igual pero con accion 'continuar' y sin advertencias
    assert "-> PA2" in r.stdout and "continuar" in r.stdout
    assert "(!)" not in r.stdout


def test_minimo_de_paradas(tmp_path, etiquetas):
    # solo hay archivos de 3 paradas: con minimo 4 la mision queda pendiente
    (tmp_path / "etiquetas" / "PM1.png").unlink()
    (tmp_path / "etiquetas" / "PM2.png").unlink()
    (tmp_path / "etiquetas" / "PM3.png").unlink()
    r = correr(tmp_path, {"minimo_paradas": 4})
    assert "mision             : 3/4 (pendiente)" in r.stdout
    r = correr(tmp_path, {"minimo_paradas": 3})
    assert "mision             : 3/3 (CUMPLIDA)" in r.stdout


def test_detecta_parada_salteada(tmp_path, etiquetas):
    (tmp_path / "etiquetas" / "PA2.png").unlink()
    r = correr(tmp_path, {})
    assert "(!) sin leer: PA2" in r.stdout
    assert "SIN LEER           : PA2" in r.stdout


def test_un_qr_ajeno_se_reporta_una_sola_vez(tmp_path, etiquetas):
    """Regresion: un QR ajeno sostenido sumaba un descarte por cuadro."""
    qrcode.make("https://ejemplo.org").save(tmp_path / "etiquetas" / "PZ_ajeno.png")
    r = correr(tmp_path, {"captura": {"tipo": "archivos",
                                      "patron": str(tmp_path / "etiquetas" / "P*.png"),
                                      "repeticiones": 40}})
    assert r.stdout.count("descartado (no es del proyecto)") == 1
    assert "1 distinto(s), 40 descarte(s)" in r.stdout


def test_configuracion_invalida_da_un_mensaje_claro(tmp_path, etiquetas):
    r = correr(tmp_path, {"paradas_activas": ["PA9"]})
    assert r.returncode == 1
    assert "Configuracion invalida" in r.stderr
    assert "PA9" in r.stderr
    assert "Traceback" not in r.stderr

    r = correr(tmp_path, {"paradas_activas": ["PA1"], "minimo_paradas": 2})
    assert r.returncode == 1 and "Nunca se podria cumplir" in r.stderr


def test_estado_local_y_reporte(tmp_path, etiquetas):
    estado, reporte = tmp_path / "estado.json", tmp_path / "rep.json"
    r = correr(tmp_path, {"estado_local": str(estado)},
               "--reporte", str(reporte), "--etiqueta", "prueba automatica")
    assert r.returncode == 0, r.stderr

    e = json.loads(estado.read_text(encoding="utf-8"))
    assert e["parada"]["id"] == "PM3" and e["mision"]["cumplida"] is True

    rep = json.loads(reporte.read_text(encoding="utf-8"))
    assert rep["etiqueta"] == "prueba automatica"
    assert rep["mision_cumplida"] is True
    assert rep["cobertura_pct"] == 100.0


def test_un_config_viejo_con_las_seis_listadas_sigue_andando(tmp_path, etiquetas):
    """Quien ya tiene un config.json anterior no debe recibir advertencias
    falsas al activar solo algunas paradas."""
    r = correr(tmp_path, {"paradas_activas": ["PA1", "PA3"],
                          "secuencia_recorrido": ["PA1", "PA2", "PA3", "PM1", "PM2", "PM3"]})
    assert "(!)" not in r.stdout
    assert "mision             : 2/2 (CUMPLIDA)" in r.stdout


class TestMapaDeEtiquetas:
    def leer(self, destino):
        with (destino / "mapa_etiquetas.csv").open(encoding="utf-8") as f:
            return {fila["parada"]: fila for fila in csv.DictReader(f)}

    def marcar(self, destino, paradas):
        filas = list(self.leer(destino).values())
        for f in filas:
            if f["parada"] in paradas:
                f["instalada"] = f["verificada"] = "SI"
        with (destino / "mapa_etiquetas.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=generar_etiquetas.CAMPOS_MAPA)
            w.writeheader()
            w.writerows(filas)

    def test_reimprimir_una_no_borra_el_registro_de_las_otras(self, etiquetas):
        """Regresion: reimprimir una sola dejaba el mapa con una fila."""
        self.marcar(etiquetas, {"PA1", "PA2"})
        generar_etiquetas.generar(["PM3"], 100, etiquetas)
        mapa = self.leer(etiquetas)
        assert len(mapa) == 6
        assert mapa["PA1"]["instalada"] == "SI" and mapa["PA2"]["verificada"] == "SI"

    def test_una_etiqueta_regenerada_vuelve_a_pendiente(self, etiquetas):
        self.marcar(etiquetas, {"PA1"})
        generar_etiquetas.generar(["PA1"], 100, etiquetas)
        assert self.leer(etiquetas)["PA1"]["instalada"] == "NO"

    def test_queda_en_el_orden_del_circuito(self, etiquetas):
        generar_etiquetas.generar(["PM3", "PA1"], 100, etiquetas)
        assert list(self.leer(etiquetas)) == ["PA1", "PA2", "PA3", "PM1", "PM2", "PM3"]
