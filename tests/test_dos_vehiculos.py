import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dos_vehiculos  # noqa: E402
from dos_vehiculos import ArgumentosInvalidos, armar_configs  # noqa: E402

BASE = {
    "id_rover": "VHC-001",
    "estado_local": "datos/estado.json",
    "publicacion": {"tipo": "mqtt", "buffer": "datos/pendientes.jsonl"},
    "captura": {"tipo": "red", "url": "http://IP_DE_LA_LAPTOP:8080/video"},
    "_notas": {"x": "y"},
    "mqtt": {"host": "IP_DE_LA_LAPTOP", "port": 1883, "vehicle_id": "VHC-001",
             "usuario": "no-deberia-quedar", "clave": "tampoco"},
}
DOS = [("VHC-005", "http://a:8080/video", "P1"), ("VHC-006", "http://b:8080/video", "P2")]


def test_cada_vehiculo_tiene_lo_suyo(tmp_path):
    r = armar_configs(BASE, DOS, "192.168.0.13", 1883, tmp_path)
    assert [x[0] for x in r] == ["VHC-005", "VHC-006"]
    c1, c2 = r[0][2], r[1][2]
    assert (c1["id_rover"], c1["mqtt"]["vehicle_id"], c1["parada_home"]) == ("VHC-005", "VHC-005", "P1")
    assert (c2["id_rover"], c2["mqtt"]["vehicle_id"], c2["parada_home"]) == ("VHC-006", "VHC-006", "P2")
    assert c1["captura"]["url"] != c2["captura"]["url"]
    # archivos de estado y buffer separados: si no, un nodo pisa al otro
    assert c1["estado_local"] != c2["estado_local"]
    assert c1["publicacion"]["buffer"] != c2["publicacion"]["buffer"]
    assert c1["mqtt"]["host"] == c2["mqtt"]["host"] == "192.168.0.13"


def test_las_credenciales_nunca_se_escriben(tmp_path):
    r = armar_configs(BASE, DOS, "h", 1883, tmp_path)
    for _, ruta, cfg in r:
        assert cfg["mqtt"]["usuario"] is None and cfg["mqtt"]["clave"] is None
        texto = Path(ruta).read_text(encoding="utf-8")
        assert "no-deberia-quedar" not in texto and "tampoco" not in texto
        assert json.loads(texto)["id_rover"] == cfg["id_rover"]


def test_no_modifica_el_config_base(tmp_path):
    copia = json.loads(json.dumps(BASE))
    armar_configs(BASE, DOS, "h", 1883, tmp_path)
    assert BASE == copia


@pytest.mark.parametrize("vehiculos, msg", [
    ([("A", "u1", "P1"), ("A", "u2", "P2")], "ids distintos"),
    ([("A", "u1", "P1"), ("B", "u2", "P1")], "home distinto"),
    ([("A", "u1", "P1"), ("B", "u1", "P2")], "misma camara"),
    ([("A", "u1", "P9"), ("B", "u2", "P2")], "no existe"),
])
def test_rechaza_configuraciones_que_se_pisarian(tmp_path, vehiculos, msg):
    with pytest.raises(ArgumentosInvalidos, match=msg):
        armar_configs(BASE, vehiculos, "h", 1883, tmp_path)


def test_solo_generar_por_linea_de_comandos(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "dos_vehiculos.py", "--cam1", "http://a/video", "--v2", "VHC-006", "--cam2", "http://b/video",
        "--broker", "192.168.0.13", "--destino", str(tmp_path), "--solo-generar"])
    assert dos_vehiculos.main() == 0
    salida = capsys.readouterr().out
    assert "VHC-005" in salida and "VHC-006" in salida and "192.168.0.13" in salida
    assert (tmp_path / "cfg-VHC-005.json").exists() and (tmp_path / "cfg-VHC-006.json").exists()


def test_sin_broker_avisa_en_vez_de_arrancar(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.setattr(sys, "argv", [
        "dos_vehiculos.py", "--cam1", "http://a/video", "--v2", "VHC-006", "--cam2", "http://b/video",
        "--destino", str(tmp_path)])
    assert dos_vehiculos.main() == 1
    assert "Falta el broker" in capsys.readouterr().err
