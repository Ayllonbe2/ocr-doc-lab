"""Extracción de campos del anverso a partir de líneas del OCR con su caja."""
import pytest
from fastapi.testclient import TestClient

from mrzlab import anverso as a, motores, sintetico as s
from mrzlab.anverso import Linea


def _dni40(**cambios) -> list[Linea]:
    """Líneas como las devolvería el OCR de un DNI 4.0 (etiqueta pequeña, valor debajo)."""
    lineas = {
        "cab": Linea("DOCUMENTO NACIONAL DE IDENTIDAD", (40, 60, 500, 20)),
        "dni": Linea("DNI 99999999R", (700, 40, 300, 40)),
        "e_ap": Linea("APELLIDOS", (440, 200, 120, 18)),
        "ap1": Linea("ESPAÑOLA", (440, 225, 180, 30)),
        "ap2": Linea("ESPAÑOLA", (440, 262, 180, 30)),
        "e_nom": Linea("NOMBRE", (440, 330, 90, 18)),
        "nom": Linea("CARMEN", (440, 355, 140, 30)),
        "e_sexo": Linea("SEXO", (440, 430, 60, 18)),
        "sexo": Linea("F", (440, 455, 20, 30)),
        "e_nac": Linea("NACIONALIDAD", (620, 430, 150, 18)),
        "nac": Linea("ESP", (620, 455, 60, 30)),
        "e_fn": Linea("FECHA DE NACIMIENTO", (900, 430, 240, 18)),
        "fn": Linea("01 01 1980", (900, 455, 170, 30)),
        "e_sop": Linea("NUM SOPORTE", (440, 530, 140, 18)),
        "sop": Linea("BAA000589", (440, 555, 170, 30)),
        "e_val": Linea("VALIDEZ", (900, 530, 90, 18)),
        "val": Linea("01 01 2031", (900, 555, 170, 30)),
        "e_can": Linea("CAN", (1030, 700, 50, 18)),
        "can": Linea("123456", (1030, 725, 110, 30)),
    }
    lineas.update(cambios)
    return [ln for ln in lineas.values() if ln is not None]


def test_extrae_todos_los_campos_del_dni_40():
    r = a.extraer(_dni40())
    assert r["dni_valido"]
    assert r["campos"] == {
        "dni": "99999999R", "num_soporte": "BAA000589", "apellidos": "ESPAÑOLA ESPAÑOLA",
        "nombre": "CARMEN", "sexo": "F", "nacionalidad": "ESP", "fecha_nacimiento": "01/01/1980",
        "fecha_expedicion": None, "fecha_caducidad": "01/01/2031", "can": "123456",
    }
    assert a.parece_anverso(r)


def test_letra_del_dni_incorrecta_no_valida():
    r = a.extraer(_dni40(dni=Linea("DNI 99999999T", (700, 40, 300, 40))))
    assert r["campos"]["dni"] == "99999999T" and not r["dni_valido"]


def test_corrige_confusiones_del_ocr_en_el_dni():
    # «O» por 0 y «B» por 8 en el número; «2» por Z en la letra.
    assert a.buscar_dni("DNI 0000000OT") == ("00000000T", True)
    assert a.buscar_dni("DNI 1234567B-2") == ("12345678Z", True)
    # Una palabra no es un número de DNI.
    assert a.buscar_dni("BOLIGOSS A") is None
    assert a.buscar_dni("sin numero") is None


def test_etiquetas_con_errores_de_ocr_y_bilingues():
    assert "fecha_nacimiento" in a.etiquetas_de("FECHA DE NACIMlENTO / DATA DE NAIXEMENT")
    assert "apellidos" in a.etiquetas_de("APELLIDOS / COGNOMS")
    assert a.etiquetas_de("CARMEN") == set()


def test_dni_30_con_primer_y_segundo_apellido():
    lineas = [
        Linea("PRIMER APELLIDO", (440, 200, 180, 18)), Linea("GARCIA", (440, 225, 140, 30)),
        Linea("SEGUNDO APELLIDO", (440, 280, 190, 18)), Linea("LOPEZ", (440, 305, 120, 30)),
        Linea("NOMBRE", (440, 360, 90, 18)), Linea("ANA", (440, 385, 80, 30)),
    ]
    r = a.extraer(lineas)
    assert r["campos"]["apellidos"] == "GARCIA LOPEZ" and r["campos"]["nombre"] == "ANA"


def test_fechas_sin_etiqueta_se_deducen_por_el_anio():
    r = a.extraer([Linea("01 01 1980", None), Linea("01 01 2031", None)])
    assert r["campos"]["fecha_nacimiento"] == "01/01/1980"
    assert r["campos"]["fecha_caducidad"] == "01/01/2031"


@pytest.mark.parametrize("motor", [m.nombre for m in motores.TODOS])
def test_lee_anverso_sintetico(motor):
    import cv2
    from mrzlab.app import app
    m = next(x for x in motores.TODOS if x.nombre == motor)
    if not m.disponible()[0]:
        pytest.skip(f"{motor} no disponible en este entorno")
    jpg = cv2.imencode(".jpg", s.anverso(), [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
    r = TestClient(app).post("/api/analizar", data={"motores_sel": motor},
                             files={"archivo": ("dni.jpg", jpg, "image/jpeg")})
    assert r.status_code == 200
    datos = r.json()
    assert datos["lado"] == "anverso"
    res = datos["motores"][0]["texto"]
    assert res["lineas"], res
    assert res["anverso"]["campos"]["dni"] == "99999999R" and res["anverso"]["dni_valido"], res
