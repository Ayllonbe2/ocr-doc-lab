"""Preparar páginas: hoja en la foto, orientación, inclinación y calidad de documentos."""
import numpy as np
import pytest

from mrzlab import calidad, motores, ocr_documento, pagina
from mrzlab import sintetico_docs as sd

UMBRALES = calidad.cargar_umbrales(__import__("pathlib").Path(__file__).resolve().parent.parent / "umbrales.yaml")


def _pagina(tipo="certificado_tgss", ppp=150):
    pdf, _ = sd.generar(tipo, np.random.default_rng(1))
    return sd.a_imagen(pdf, ppp)


def test_hoja_en_una_foto_se_encuentra_y_endereza():
    img = _pagina()
    foto = sd.foto(img, np.random.default_rng(2), fuerza=0.5)
    esquinas = pagina.buscar_hoja(foto)
    assert esquinas is not None
    plana = pagina.enderezar_hoja(foto, esquinas)
    alto, ancho = plana.shape[:2]
    assert abs(alto / ancho - img.shape[0] / img.shape[1]) < 0.08     # proporción de A4


def test_escaneo_sin_hoja_que_buscar():
    assert pagina.buscar_hoja(_pagina()) is None


@pytest.mark.parametrize("angulo", [-3.0, 2.0])
def test_inclinacion(angulo):
    img = pagina.rotar(_pagina(), angulo)
    assert abs(pagina.inclinacion(img) + angulo) <= 0.5


@pytest.mark.parametrize("giro", [90, 180, 270])
def test_orientacion(giro):
    if not motores.Tesseract().disponible()[0]:
        pytest.skip("sin Tesseract")
    img = pagina.girar(_pagina(ppp=200), giro)
    assert (giro + pagina.orientacion(img)) % 360 == 0


def test_escaneo_limpio_frente_a_foto():
    img = _pagina()
    assert ocr_documento.escaneo_limpio(img)
    assert not ocr_documento.escaneo_limpio(sd.foto(img, np.random.default_rng(3)))


def test_calidad_escaneo_limpio_es_apta():
    ev = calidad.evaluar_documento(_pagina(ppp=200), UMBRALES, altura_letra=30)
    assert ev.veredicto == "apta", ev.avisos


def test_papel_blanco_no_es_reflejo():
    """Con la medida del DNI, un escaneo (papel casi a 255) salía entero como reflejo."""
    assert calidad.reflejo_papel(_pagina()) < 0.01


def test_calidad_foto_borrosa_y_letra_pequena():
    import cv2
    borrosa = cv2.GaussianBlur(_pagina(ppp=200), (0, 0), 6)
    ev = calidad.evaluar_documento(borrosa, UMBRALES, altura_letra=8)
    assert ev.veredicto == "rechazar"
    mensajes = " ".join(a["mensaje"] for a in ev.avisos)
    assert "borrosa" in mensajes and "pequeño" in mensajes


def test_espaciar_palabras_pegadas():
    assert ocr_documento.espaciar("conDNI1.234.567-L,de1985") == "con DNI 1.234.567-L, de 1985"


def test_combinar_motores_sin_duplicar():
    from mrzlab.lineas import Linea
    t = [Linea("en Madrid, con DNI 12345678Z", (0.5, 0.3, 0.3, 0.02), 1, "ocr:tesseract", 0.9)]
    r = [Linea("nacido el dia 1 de enero en Madrid, con DNI 12345678Z", (0.2, 0.3, 0.6, 0.02), 1, "ocr:rapidocr", 0.95),
         Linea("Título de Técnico", (0.2, 0.4, 0.3, 0.02), 1, "ocr:rapidocr", 0.95)]
    salida = ocr_documento.combinar(t, r)
    # Tesseract solo cubre la mitad de la primera línea: vale la de RapidOCR, sin duplicar.
    assert [ln.texto for ln in salida] == [r[0].texto, r[1].texto]
