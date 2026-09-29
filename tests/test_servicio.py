"""Verificación del DNI: la decisión (sin OCR) y el proceso completo con DNI sintéticos.

Todos los datos son ficticios.
"""
import cv2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mrzlab import sintetico as s
from mrzlab import motores, mrz
from servicio.api import router
from servicio.lectura import Calidad, LecturaAnverso, LecturaReverso
from servicio.verificacion import Estado, Motivo, decidir, normalizar_dni

DNI = "12345678Z"
SOPORTE = "BAA000589"
MRZ = s.construir_mrz(SOPORTE, DNI[:8], "900417", "M", "341002", "GOMEZ RUIZ", "LUIS")
BUENA, MALA = Calidad("apta"), Calidad("rechazar", ["La foto está borrosa."])


def _rev(lineas=MRZ, cal=BUENA):
    return LecturaReverso(mrz.leer(lineas) if lineas else None, cal)


def _anv(dnis=(DNI,), soportes=(SOPORTE,), cal=BUENA):
    return LecturaAnverso(list(dnis), list(soportes), cal)


# ── Decisión ─────────────────────────────────────────────────────────────────

def test_todo_coincide_verificado():
    r = decidir(_anv(), _rev(), "12345678-z", 1)
    assert r.estado is Estado.VERIFICADO and r.motivo is Motivo.OK
    assert all(r.comprobaciones.values())
    assert r.datos_reverso == {"dni": DNI, "num_soporte": SOPORTE, "nombre": "LUIS",
                               "apellidos": "GOMEZ RUIZ", "nacionalidad": "ESP",
                               "fecha_nacimiento": "17/04/1990", "fecha_caducidad": "02/10/2034"}
    assert r.datos_anverso == {"dni": DNI, "num_soporte": SOPORTE}


def test_dni_declarado_distinto_va_al_admin():
    r = decidir(_anv(), _rev(), "87654321X", 1)
    assert r.estado is Estado.REVISION_ADMIN and r.motivo is Motivo.DATOS_NO_COINCIDEN
    assert r.comprobaciones["dni_reverso_igual_declarado"] is False


def test_soporte_distinto_va_al_admin_aunque_sea_el_primer_intento():
    r = decidir(_anv(soportes=("BAA000590",)), _rev(), DNI, 1)
    assert r.estado is Estado.REVISION_ADMIN and r.motivo is Motivo.DATOS_NO_COINCIDEN
    assert r.comprobaciones["soporte_anverso_igual_reverso"] is False


def test_del_anverso_se_elige_el_candidato_que_coincide_con_la_mrz():
    r = decidir(_anv(soportes=("BAA000598", SOPORTE)), _rev(), DNI, 1)
    assert r.estado is Estado.VERIFICADO


def test_soporte_pegado_a_otro_texto_en_el_anverso_vale_si_coincide_con_la_mrz():
    anv = LecturaAnverso([DNI], [], BUENA, texto="NUMSOPORTE|BAA00058902102024")
    assert decidir(anv, _rev(), DNI, 1).estado is Estado.VERIFICADO
    # Si el texto no lo contiene, sigue sin leerse.
    anv = LecturaAnverso([DNI], [], BUENA, texto="NUMSOPORTE|BAA00O58902102024")
    assert decidir(anv, _rev(), DNI, 1).motivo is Motivo.LECTURA_FALLIDA


def test_mala_calidad_pide_repetir_y_la_segunda_vez_va_al_admin():
    r = decidir(_anv(), _rev(lineas=None, cal=MALA), DNI, 1)
    assert r.estado is Estado.REPETIR and r.motivo is Motivo.MALA_CALIDAD
    assert r.instrucciones == ["Reverso: La foto está borrosa."]
    r = decidir(_anv(), _rev(lineas=None, cal=MALA), DNI, 2)
    assert r.estado is Estado.REVISION_ADMIN and r.motivo is Motivo.INTENTOS_AGOTADOS


def test_anverso_sin_soporte_y_con_mala_calidad_pide_repetir():
    r = decidir(_anv(soportes=(), cal=MALA), _rev(), DNI, 1)
    assert r.estado is Estado.REPETIR and r.instrucciones[0].startswith("Anverso:")


def test_no_se_lee_con_buena_calidad_va_directo_al_admin():
    r = decidir(_anv(), _rev(lineas=None, cal=BUENA), DNI, 1)
    assert r.estado is Estado.REVISION_ADMIN and r.motivo is Motivo.LECTURA_FALLIDA


def test_mala_calidad_en_la_cara_que_si_se_lee_no_cuenta():
    # El reverso falla con buena calidad; el anverso tiene mala calidad pero se ha leído.
    r = decidir(_anv(cal=MALA), _rev(lineas=None, cal=BUENA), DNI, 1)
    assert r.motivo is Motivo.LECTURA_FALLIDA


def test_dni_caducado_se_avisa():
    caducado = s.construir_mrz(SOPORTE, DNI[:8], "900417", "M", "200101", "GOMEZ RUIZ", "LUIS")
    r = decidir(_anv(), _rev(caducado), DNI, 1)
    assert r.estado is Estado.VERIFICADO and r.avisos == ["El DNI está caducado."]


def test_normalizar_dni():
    assert normalizar_dni(" 12.345.678-z ") == "12345678Z"


# ── Proceso completo (API) ───────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)
cliente = TestClient(app)


def _jpg(img):
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


def _post(anverso, reverso, dni, intento=1):
    return cliente.post("/v1/dni/verificar", data={"dni_declarado": dni, "intento": intento},
                        files={"anverso": ("a.jpg", _jpg(anverso), "image/jpeg"),
                               "reverso": ("r.jpg", _jpg(reverso), "image/jpeg")})


def _hay_motores():
    if not any(m.disponible()[0] for m in motores.TODOS):
        pytest.skip("sin motores OCR en este entorno")


def _persona():
    anverso = s.anverso({"dni": DNI, "soporte": SOPORTE, "apellidos": ["GOMEZ", "RUIZ"],
                         "nombre": "LUIS", "sexo": "M", "nacimiento": "17 04 1990",
                         "emision": "02 10 2024", "validez": "02 10 2034"})
    return anverso, s.reverso(MRZ)


def test_api_verifica_un_dni_sintetico():
    _hay_motores()
    r = _post(*_persona(), DNI)
    assert r.status_code == 200
    d = r.json()
    assert d["estado"] == "VERIFICADO", d
    assert d["datos_reverso"]["nombre"] == "LUIS" and d["datos_anverso"]["num_soporte"] == SOPORTE
    # La respuesta no lleva imágenes ni texto bruto del OCR.
    assert not any(k in d for k in ("imagen", "texto", "raw_output"))


def test_api_dni_declarado_distinto():
    _hay_motores()
    d = _post(*_persona(), "87654321X").json()
    assert d["estado"] == "REVISION_ADMIN" and d["motivo"] == "DATOS_NO_COINCIDEN"


def test_api_foto_borrosa_pide_repetir():
    _hay_motores()
    anverso, reverso = _persona()
    d = _post(anverso, s.desenfocar(reverso, 25), DNI).json()
    assert d["estado"] == "REPETIR" and d["instrucciones"], d
    d = _post(anverso, s.desenfocar(reverso, 25), DNI, intento=2).json()
    assert d["estado"] == "REVISION_ADMIN" and d["motivo"] == "INTENTOS_AGOTADOS"


@pytest.mark.parametrize("intento", [0, 3])
def test_api_rechaza_intento_fuera_de_rango(intento):
    r = _post(*_persona(), DNI, intento)
    assert r.status_code == 400


def _app_con_entorno(monkeypatch, **entorno):
    """Importa (o recarga) servicio.app con estas variables de entorno."""
    import importlib
    import sys
    for clave in ("OCR_API_KEY", "OCR_ALLOW_ANONYMOUS"):
        monkeypatch.delenv(clave, raising=False)
    for clave, valor in entorno.items():
        monkeypatch.setenv(clave, valor)
    if "servicio.app" in sys.modules:
        return importlib.reload(sys.modules["servicio.app"])
    return importlib.import_module("servicio.app")


def test_app_exige_api_key_salvo_en_health(monkeypatch):
    app_ = TestClient(_app_con_entorno(monkeypatch, OCR_API_KEY="secreta").app)
    assert app_.get("/health").status_code == 200
    assert _post_con(app_, {}).status_code == 401
    assert _post_con(app_, {"X-Api-Key": "otra"}).status_code == 401
    assert _post_con(app_, {"X-Api-Key": "secreta"}).status_code == 400  # llega: no es imagen


def test_app_no_arranca_sin_api_key(monkeypatch):
    with pytest.raises(RuntimeError):
        _app_con_entorno(monkeypatch)


def _post_con(cliente_, cabeceras):
    return cliente_.post("/v1/dni/verificar", headers=cabeceras, data={"dni_declarado": DNI},
                         files={"anverso": ("a.jpg", b"no", "image/jpeg"), "reverso": ("r.jpg", b"no", "image/jpeg")})


def test_las_fotos_subidas_no_se_escriben_en_disco():
    from starlette.formparsers import MultiPartParser
    from servicio.api import ATRIBUTO_SPOOL, MAX_BYTES
    # Por debajo de este tamaño Starlette mantiene el archivo en memoria (SpooledTemporaryFile).
    assert getattr(MultiPartParser, ATRIBUTO_SPOOL) > MAX_BYTES


def test_api_rechaza_lo_que_no_es_imagen():
    r = cliente.post("/v1/dni/verificar", data={"dni_declarado": DNI},
                     files={"anverso": ("a.jpg", b"no", "image/jpeg"), "reverso": ("r.jpg", b"no", "image/jpeg")})
    assert r.status_code == 400
