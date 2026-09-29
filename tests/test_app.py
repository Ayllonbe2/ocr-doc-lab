"""Prueba de extremo a extremo: API + motores disponibles sobre imágenes sintéticas."""
import cv2
import pytest
from fastapi.testclient import TestClient

from mrzlab import motores, sintetico as s
from mrzlab.app import app

cliente = TestClient(app)


def _jpeg(img):
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


def test_estado():
    r = cliente.get("/api/estado")
    assert r.status_code == 200
    assert {m["nombre"] for m in r.json()["motores"]} == {"rapidocr", "tesseract"}


def test_rechaza_archivo_que_no_es_imagen():
    r = cliente.post("/api/analizar", files={"archivo": ("x.jpg", b"no soy una imagen", "image/jpeg")})
    assert r.status_code == 400


@pytest.mark.parametrize("motor", [m.nombre for m in motores.TODOS])
def test_lee_mrz_sintetica(motor):
    m = next(x for x in motores.TODOS if x.nombre == motor)
    if not m.disponible()[0]:
        pytest.skip(f"{motor} no disponible en este entorno")
    r = cliente.post("/api/analizar", data={"motores_sel": motor},
                     files={"archivo": ("dni.jpg", _jpeg(s.reverso()), "image/jpeg")})
    assert r.status_code == 200
    datos = r.json()
    assert datos["calidad"]["veredicto"] == "apta"
    res = datos["motores"][0]
    assert res["mrz"]["valido"], res
    assert res["mrz"]["campos"]["dni"] == "99999999R"


def test_muestras():
    nombres = cliente.get("/api/muestras").json()
    assert "limpia" in nombres
    r = cliente.get("/api/muestras/borrosa.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


def test_telemetria_onnxruntime_desactivada():
    # ONNX Runtime envía telemetría a Microsoft por defecto; el laboratorio no debe conectar fuera.
    import os
    import mrzlab  # noqa: F401
    assert os.environ.get("ORT_DISABLE_TELEMETRY") == "1"


def test_combinado_elige_el_primero_valido():
    from mrzlab import analisis
    valido = {"valido": True, "controles": {"a": True}}
    invalido = {"valido": False, "controles": {"a": False}}
    base = {"disponible": True, "error": None, "intento": "x", "texto_bruto": []}
    res = [{**base, "motor": "tesseract", "ms": 300, "mrz": invalido},
           {**base, "motor": "rapidocr", "ms": 2000, "mrz": valido}]
    c = analisis._combinado(res)
    assert c["mrz"] is valido and c["ms"] == 2300 and c["intento"].startswith("rapidocr")
    res[0]["mrz"] = valido
    c = analisis._combinado(res)
    assert c["ms"] == 300 and c["intento"].startswith("tesseract")
    assert analisis._combinado(res[:1]) is None
