"""Rellena formularios oficiales en blanco con datos ficticios, para medir con maquetas reales.

    python -m herramientas.rellenar_formularios datos/publicos datos/formularios

Busca en la carpeta de origen los modelos que conoce (se descargan a mano de sus sedes; no se
incluyen en el repositorio) y deja en la de destino, por cada uno, tres versiones y su verdad.csv:

- `*-formulario.pdf`: relleno en el propio PDF, sin aplanar (los datos van en anotaciones);
- `*-aplanado.pdf`: con los datos impresos en la página (como al «Imprimir a PDF»);
- `*-escaneado.pdf`: el aplanado, impreso y escaneado (solo imagen).

Modelos:
- `sepe-contrato-indefinido.pdf`: contrato de trabajo indefinido del SEPE (sepe.es → Empresas →
  Contratos de trabajo → Modelos de contrato).
- `epis-irnas.pdf`: registro de entrega de EPI con campos de formulario (publicado por un centro
  del CSIC).
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import numpy as np

from mrzlab import sintetico_docs as sd


def _rellenar(origen: Path, valores: dict[str, str], firmas: list[tuple[int, float, float]] = ()) -> bytes:
    from pypdf import PdfReader, PdfWriter
    lector = PdfReader(str(origen))
    w = PdfWriter()
    w.append(lector)
    for pagina in w.pages:
        w.update_page_form_field_values(pagina, valores, auto_regenerate=False)
    w.set_need_appearances_writer(True)
    if firmas:
        _firmar_encima(w, firmas)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _firmar_encima(w, firmas: list[tuple[int, float, float]]) -> None:
    """Garabato de firma (dibujado con reportlab) encima de la página, en (x, y) en puntos."""
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas
    rng = np.random.default_rng(7)
    for pagina, x, y in firmas:
        p = w.pages[pagina]
        ancho, alto = float(p.mediabox.width), float(p.mediabox.height)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(ancho, alto))
        c.setStrokeColorRGB(0.05, 0.1, 0.45)
        c.setLineWidth(1.2)
        trazo = c.beginPath()
        px, py = x, alto - y
        trazo.moveTo(px, py)
        for _ in range(5):
            dx = float(rng.uniform(12, 24))
            puntos = [(px + dx * f, py + float(rng.uniform(-10, 10))) for f in (0.33, 0.66, 1.0)]
            trazo.curveTo(*[v for par in puntos for v in par])
            px, py = puntos[-1]
        c.drawPath(trazo, stroke=1, fill=0)
        c.save()
        p.merge_page(PdfReader(buf).pages[0])


def _aplanar(pdf: bytes) -> bytes:
    """Imprime los valores del formulario en la página (render con pypdfium2 y vuelta a PDF)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf)
    doc.init_forms()
    imagenes = []
    for i in range(len(doc)):
        imagenes.append(np.array(doc[i].render(scale=200 / 72, may_draw_forms=True).to_pil().convert("RGB"))[:, :, ::-1])
    doc.close()
    return sd.pdf_de_imagen(imagenes, 200)


def contrato(modelo: Path, rng) -> tuple[bytes, dict]:
    nombre, apellidos, dni = sd.persona(rng)
    _, representante, dni_rep = sd.persona(rng)
    ident = sd.cif(rng)
    razon = f"{rng.choice(sd.EMPRESAS)} SL"
    inicio = sd.fecha(rng, 10, 300)
    valores = {"AA0101-E09": ident, "AA0102": f"PEDRO {representante}", "AA0103-E09": dni_rep,
               "AA0104": "ADMINISTRADOR", "AA0105": razon, "AA0106": "CALLE INVENTADA 1", "AA0107": "MADRID",
               "AA0401": f"{nombre} {apellidos}", "AA0402-E09": dni, "AA0403-FE-E10": "12/05/1990",
               "AA0405": "ESPAÑOLA", "C0101": "RECURSO PREVENTIVO", "C0401-FE": sd.num(inicio)}
    verdad = {"identificador_empresa": ident, "razon_social": razon, "nif_trabajador": dni,
              "nombre_trabajador": f"{nombre} {apellidos}", "fecha_inicio": inicio.isoformat(),
              "tipo_contrato": "INDEFINIDO"}
    return _rellenar(modelo, valores), verdad


def epis(modelo: Path, rng, firmada: bool = True) -> tuple[bytes, dict]:
    nombre, apellidos, _ = sd.persona(rng)
    _, responsable, _ = sd.persona(rng)
    entrega = sd.fecha(rng, 5, 200)
    valores = {"Responsable": f"MARTA {responsable}", "Servicio/grupo": "GRUPO DE PRUEBAS",
               "Personal que se incorpora": f"{nombre} {apellidos}", "EPI": "CASCO", "Marca": "EJEMPLO",
               "Modelo": "X1", "Unidades": "1", "FECHA": sd.num(entrega), "FECHA_2": sd.num(entrega)}
    # Firmas en la página 2, a la derecha de «FIRMA RESPONSABLE» y «FIRMA PERSONA QUE SE INCORPORA».
    firmas = [(1, 400, 196)] + ([(1, 400, 219)] if firmada else [])
    verdad = {"nombre_trabajador": f"{nombre} {apellidos}", "fecha": entrega.isoformat(), "firmado": firmada}
    return _rellenar(modelo, valores, firmas), verdad


MODELOS = {"sepe-contrato-indefinido.pdf": ("contrato_laboral", contrato),
           "epis-irnas.pdf": ("entrega_epis", epis)}


def main(origen: Path, destino: Path, n: int = 2) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    filas = []
    for archivo, (tipo, generar) in MODELOS.items():
        modelo = origen / archivo
        if not modelo.exists():
            print(f"  (no está {modelo}: se omite)")
            continue
        for i in range(n):
            rng = np.random.default_rng(100 + i)
            opciones = {"firmada": i % 2 == 0} if tipo == "entrega_epis" else {}
            pdf, verdad = generar(modelo, rng, **opciones)
            base = f"{Path(archivo).stem}-{i}"
            aplanado = _aplanar(pdf)
            escaneado = sd.escanear(aplanado, rng)
            for sufijo, datos in (("formulario", pdf), ("aplanado", aplanado), ("escaneado", escaneado)):
                nombre = f"{base}-{sufijo}.pdf"
                (destino / nombre).write_bytes(datos)
                filas += [[nombre, tipo, campo, valor] for campo, valor in verdad.items()]
            print("  escrito", base)
    with open(destino / "verdad.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["archivo", "tipo", "campo", "valor"], *filas])


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
