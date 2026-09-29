"""Plantilla de posiciones del anverso: aprender, situar la tarjeta y leer por zonas."""
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from mrzlab import anverso, motores, plantilla, sintetico as s
from mrzlab.anverso import Linea


@pytest.fixture(autouse=True)
def plantilla_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(plantilla, "RUTA", tmp_path / "anverso.yaml")


def test_aprender_promedia_y_solo_guarda_coordenadas():
    plantilla.aprender({"dni": [0.5, 0.1, 0.3, 0.05]})
    campos = plantilla.aprender({"dni": [0.6, 0.1, 0.3, 0.05], "can": [0.8, 0.9, 0.1, 0.04]})
    assert campos["dni"] == {"caja": [0.55, 0.1, 0.3, 0.05], "n": 2}
    assert campos["can"]["n"] == 1
    texto = plantilla.RUTA.read_text(encoding="utf-8")
    assert "99999999" not in texto and "sin datos personales" in texto
    plantilla.borrar()
    assert plantilla.cargar() is None


@pytest.mark.parametrize("caja", [[0.5, 0.1, 0.3], [1.5, 0.1, 0.3, 0.05], [0.5, 0.1, 0, 0.05]])
def test_aprender_rechaza_cajas_invalidas(caja):
    with pytest.raises(ValueError):
        plantilla.aprender({"dni": caja})


def test_aprender_rechaza_campos_desconocidos():
    with pytest.raises(ValueError):
        plantilla.aprender({"foto": [0.1, 0.1, 0.1, 0.1]})


def test_leer_campo_por_tipo():
    assert anverso.leer_campo("fecha_nacimiento", "17 O4 199O") == "17/04/1990"
    assert anverso.leer_campo("fecha_caducidad", "VALIDEZ 01012031") == "01/01/2031"
    assert anverso.leer_campo("nombre", "NOMBRE CARMEN") == "CARMEN"
    assert anverso.leer_campo("sexo", "SEXO F") == "F"
    assert anverso.leer_campo("can", "CAN 123456") == "123456"
    assert anverso.leer_campo("dni", "DNI 99999999R") == "99999999R"


def test_soporte_con_un_caracter_de_mas():
    assert anverso.buscar_soporte("ABC1234565") == "ABC123456"
    assert anverso.buscar_soporte("ABC123456") == "ABC123456"
    # Pegado a la fecha de emisión que tiene al lado.
    assert anverso.buscar_soporte("BAA00058902 10 2024") == "BAA000589"
    # Una fecha no es un soporte.
    assert anverso.buscar_soporte("02102024 17041990") is None


def test_zona_de_nombre_va_de_su_etiqueta_a_la_siguiente():
    plant = {"apellidos": {"caja": [0.35, 0.30, 0.15, 0.04], "n": 1},  # aprendido con 1 línea
             "etiqueta.apellidos": {"caja": [0.35, 0.26, 0.10, 0.025], "n": 1},
             "etiqueta.nombre": {"caja": [0.35, 0.42, 0.08, 0.025], "n": 1}}
    x, y, w, h = plantilla.zona("apellidos", plant["apellidos"]["caja"], plant)
    assert y < 0.30 and abs((y + h) - 0.416) < 0.001  # cabe una segunda línea hasta «NOMBRE»
    assert x + w > 0.75  # y un apellido más largo


def test_extrae_fecha_de_emision_sin_etiqueta():
    r = anverso.extraer([Linea("17041990", None), Linea("02102024", None), Linea("02102034", None)])
    assert r["campos"]["fecha_nacimiento"] == "17/04/1990"
    assert r["campos"]["fecha_expedicion"] == "02/10/2024"
    assert r["campos"]["fecha_caducidad"] == "02/10/2034"


def test_situar_por_anclas_sin_bordes():
    plant = {"dni": {"caja": [0.5, 0.05, 0.3, 0.06], "n": 1},
             "can": {"caja": [0.8, 0.85, 0.1, 0.05], "n": 1},
             "sexo": {"caja": [0.35, 0.6, 0.03, 0.05], "n": 1},
             "nombre": {"caja": [0.35, 0.45, 0.2, 0.05], "n": 1}}
    # Tarjeta de 1000 px de alto desplazada (100, 50) en una foto sin bordes visibles.
    s_, p = 1000, 85.6 / 54
    cajas = {c: (round(100 + s_ * p * v["caja"][0]), round(50 + s_ * v["caja"][1]),
                 round(s_ * p * v["caja"][2]), round(s_ * v["caja"][3])) for c, v in plant.items()}
    img = np.full((1200, 1800, 3), 128, np.uint8)
    g = plantilla.situar(img, {k: v for k, v in cajas.items() if k != "nombre"}, plant)
    assert g is not None and g.metodo.startswith("campos")
    x, y, w, h = g.rel_a_px(plant["nombre"]["caja"])
    assert abs(x - cajas["nombre"][0]) <= 2 and abs(y - cajas["nombre"][1]) <= 2


def _analizar(img, motor=None):
    from mrzlab.app import app
    jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
    datos = {"lado": "anverso", **({"motores_sel": motor} if motor else {})}
    r = TestClient(app).post("/api/analizar", data=datos, files={"archivo": ("dni.jpg", jpg, "image/jpeg")})
    assert r.status_code == 200
    return r.json()


@pytest.mark.parametrize("motor", [m.nombre for m in motores.TODOS])
def test_aprende_de_una_foto_y_lee_otra_por_posicion(motor):
    m = next(x for x in motores.TODOS if x.nombre == motor)
    if not m.disponible()[0]:
        pytest.skip(f"{motor} no disponible en este entorno")
    rapid = next(x for x in motores.TODOS if x.nombre == "rapidocr")
    if not rapid.disponible()[0]:
        pytest.skip("hace falta rapidocr para aprender")
    # Aprender con la foto limpia (los bordes de la tarjeta se ven).
    d = _analizar(s.anverso(), "rapidocr")
    propuesta = d["plantilla"]["propuesta"]
    assert d["plantilla"]["geometria"]["metodo"] == "bordes de la tarjeta"
    assert {"dni", "nombre", "fecha_nacimiento", "fecha_caducidad"} <= set(propuesta)
    plantilla.aprender(propuesta)

    # Otra persona, en otra foto: se lee por posición.
    otra = s.anverso({"dni": "12345678Z", "apellidos": ["GOMEZ", "RUIZ"], "nombre": "LUCIA",
                      "nacimiento": "17 04 1990", "emision": "02 10 2024", "validez": "02 10 2034"})
    d = _analizar(otra, motor)
    pos = d["motores"][0]["texto"]["anverso"]["posicion"]
    assert pos["dni_valido"] and pos["campos"]["dni"] == "12345678Z", pos
    assert pos["campos"]["fecha_nacimiento"] == "17/04/1990", pos
    assert pos["campos"]["fecha_caducidad"] == "02/10/2034", pos
    assert pos["campos"]["nombre"] == "LUCIA", pos


def test_aprende_con_una_linea_de_apellidos_y_lee_dos():
    rapid = next(x for x in motores.TODOS if x.nombre == "rapidocr")
    if not rapid.disponible()[0]:
        pytest.skip("hace falta rapidocr")
    d = _analizar(s.anverso({"apellidos": ["GOMEZ"]}), "rapidocr")
    assert "etiqueta.apellidos" in d["plantilla"]["propuesta"]
    plantilla.aprender(d["plantilla"]["propuesta"])
    otra = s.anverso({"dni": "12345678Z", "apellidos": ["DE LA TORRE", "FERNANDEZ"], "nombre": "LUCIA"})
    pos = _analizar(otra, "rapidocr")["motores"][0]["texto"]["anverso"]["posicion"]
    # RapidOCR a veces junta palabras («LATORRE»): se compara sin espacios.
    assert pos["campos"]["apellidos"].replace(" ", "") == "DELATORREFERNANDEZ", pos
    assert pos["campos"]["nombre"] == "LUCIA", pos
