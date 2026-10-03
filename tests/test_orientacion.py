"""Orientación: un DNI girado 90/180/270° se deja derecho antes de leerlo (datos ficticios)."""
import pytest

from mrzlab import motores, orientacion, pagina, sintetico as s

pytestmark = pytest.mark.skipif(not motores.RapidOCR().disponible()[0], reason="sin RapidOCR")

MUESTRAS = {"anverso": s.anverso, "reverso": s.reverso,
            "anverso-movil": lambda: s._movil_anverso(5), "reverso-movil": lambda: s._movil(1)}


@pytest.mark.parametrize("nombre", MUESTRAS)
@pytest.mark.parametrize("giro", [0, 90, 180, 270])
def test_endereza(nombre, giro):
    derecha = MUESTRAS[nombre]()
    # Girar la foto «giro» grados en sentido antihorario: para enderezarla hay que girarla
    # «giro» grados en sentido horario.
    girada = pagina.girar(derecha, -giro)
    img, o = orientacion.orientar(girada)
    assert o.giro == giro, o
    assert img.shape == derecha.shape


def test_analizar_lee_la_mrz_de_un_reverso_boca_abajo():
    from mrzlab import analisis, calidad
    from mrzlab.app import UMBRALES_RUTA
    img = pagina.girar(s.reverso(), 180)
    res, _ = analisis.analizar(img, calidad.cargar_umbrales(UMBRALES_RUTA), {"rapidocr"}, lado="auto")
    assert res["orientacion"]["giro"] == 180
    assert res["lado"] == "reverso"
    assert next(m for m in res["motores"] if m["motor"] == "rapidocr")["mrz"]["valido"]
