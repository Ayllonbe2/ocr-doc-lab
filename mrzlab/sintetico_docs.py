"""Documentos sintéticos de cada tipo, con datos ficticios, para tests y pruebas sin datos reales.

`generar(tipo, rng)` devuelve un PDF digital (con capa de texto) y la verdad de sus campos.
Después se puede convertir en escaneo o en foto de móvil:

    pdf, verdad = generar("flc_60h", rng)
    img = a_imagen(pdf)                    # página renderizada
    escaneado = pdf_de_imagen(escaneo(img, rng))
    foto_jpg = a_jpeg(foto(img, rng))

No imitan el diseño de ningún emisor real: son maquetas con el texto y la estructura típicos.
Todos los nombres, NIF y CIF son inventados (con letra o dígito de control válidos).
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, timedelta

import cv2
import numpy as np

from . import sintetico
from .validadores import LETRAS_DNI

NOMBRES = ("LUIS", "CARMEN", "JAVIER", "LUCIA", "PABLO", "MARTA", "DIEGO", "ELENA", "SERGIO", "NURIA")
APELLIDOS = ("GOMEZ", "RUIZ", "MARTIN", "SANZ", "IBAÑEZ", "MORENO", "CASTRO", "PEÑA", "ORTEGA", "VIDAL")
EMPRESAS = ("CONSTRUCCIONES EJEMPLO", "OBRAS Y REFORMAS FICTICIAS", "ESTRUCTURAS DE PRUEBA",
            "EDIFICACIONES INVENTADAS")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre")


# ── Datos ficticios ──────────────────────────────────────────────────────────

def nif(rng: np.random.Generator) -> str:
    n = int(rng.integers(10_000_000, 99_999_999))
    return f"{n}{LETRAS_DNI[n % 23]}"


def cif(rng: np.random.Generator) -> str:
    letra = "B"
    d = [int(x) for x in rng.integers(0, 10, 7)]
    pares = sum(d[1::2])
    impares = sum(sum(divmod(x * 2, 10)) for x in d[0::2])
    control = (10 - (pares + impares) % 10) % 10
    return letra + "".join(map(str, d)) + str(control)


def persona(rng: np.random.Generator) -> tuple[str, str, str]:
    """(nombre, «APELLIDO APELLIDO», NIF)."""
    return (str(rng.choice(NOMBRES)), f"{rng.choice(APELLIDOS)} {rng.choice(APELLIDOS)}", nif(rng))


def fecha(rng: np.random.Generator, desde_dias: int = 30, hasta_dias: int = 900) -> date:
    return date.today() - timedelta(days=int(rng.integers(desde_dias, hasta_dias)))


def en_letra(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def num(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# ── Maquetación (reportlab) ──────────────────────────────────────────────────

@dataclass
class Hoja:
    """Lienzo A4 con utilidades de texto. Coordenadas en mm desde arriba a la izquierda."""
    canvas: object
    ancho: float
    alto: float

    def texto(self, x: float, y: float, s: str, tam: float = 10, negrita: bool = False,
              centro: bool = False, color=(0, 0, 0)):
        from reportlab.lib.units import mm
        c = self.canvas
        c.setFillColorRGB(*color)
        c.setFont("Helvetica-Bold" if negrita else "Helvetica", tam)
        if centro:
            c.drawCentredString(x * mm, (self.alto - y) * mm, s)
        else:
            c.drawString(x * mm, (self.alto - y) * mm, s)

    def parrafo(self, x: float, y: float, s: str, ancho: float, tam: float = 10, interlineado: float = 5.2,
                centro: bool = False) -> float:
        """Texto partido en líneas que caben en `ancho` mm. Devuelve la y siguiente."""
        from reportlab.lib.units import mm
        from reportlab.pdfbase.pdfmetrics import stringWidth
        linea = ""
        for palabra in s.split():
            prueba = f"{linea} {palabra}".strip()
            if stringWidth(prueba, "Helvetica", tam) > ancho * mm and linea:
                self.texto(x + (ancho / 2 if centro else 0), y, linea, tam, centro=centro)
                y += interlineado
                linea = palabra
            else:
                linea = prueba
        if linea:
            self.texto(x + (ancho / 2 if centro else 0), y, linea, tam, centro=centro)
            y += interlineado
        return y

    def caja(self, x: float, y: float, w: float, h: float, color=(0.3, 0.3, 0.3), grosor: float = 0.6):
        from reportlab.lib.units import mm
        c = self.canvas
        c.setStrokeColorRGB(*color)
        c.setLineWidth(grosor)
        c.rect(x * mm, (self.alto - y - h) * mm, w * mm, h * mm)

    def campo(self, x: float, y: float, w: float, etiqueta: str, valor: str):
        """Casilla de formulario: etiqueta pequeña arriba, valor dentro de la caja."""
        self.texto(x, y, etiqueta, 7, color=(0.25, 0.25, 0.35))
        self.caja(x, y + 1.2, w, 6.5)
        if valor:
            self.texto(x + 1.5, y + 6, valor, 9.5)

    def orla(self):
        """Marco decorativo de diploma (dos bordes de color y esquinas)."""
        self.caja(8, 8, self.ancho - 16, self.alto - 16, color=(0.55, 0.12, 0.15), grosor=2.2)
        self.caja(11, 11, self.ancho - 22, self.alto - 22, color=(0.2, 0.3, 0.55), grosor=0.8)
        from reportlab.lib.units import mm
        c = self.canvas
        c.setStrokeColorRGB(0.8, 0.85, 0.9)
        c.setLineWidth(0.3)
        for i in range(0, int(self.ancho), 6):     # fondo de seguridad: líneas finas diagonales
            c.line(i * mm, 12 * mm, (i + 30) * mm, (self.alto - 12) * mm)

    def firma(self, x: float, y: float, rng: np.random.Generator):
        """Garabato de firma manuscrita (curvas de Bézier)."""
        from reportlab.lib.units import mm
        c = self.canvas
        c.setStrokeColorRGB(0.05, 0.1, 0.45)
        c.setLineWidth(1.1)
        p = c.beginPath()
        px, py = x, y
        p.moveTo(px * mm, (self.alto - py) * mm)
        for _ in range(5):
            dx = float(rng.uniform(6, 12))
            puntos = [(px + dx * f, py + float(rng.uniform(-6, 6))) for f in (0.33, 0.66, 1.0)]
            p.curveTo(*[v for (a, b) in puntos for v in (a * mm, (self.alto - b) * mm)])
            px, py = puntos[-1]
        c.drawPath(p, stroke=1, fill=0)


def _pdf(dibujar, apaisado: bool = False, paginas: int = 1) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    tam = landscape(A4) if apaisado else A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=tam)
    c.setTitle("Documento de prueba")
    c.setProducer("sintetico_docs")
    hoja = Hoja(c, tam[0] / 2.834645669, tam[1] / 2.834645669)
    for i in range(paginas):
        dibujar(hoja, i)
        c.showPage()
    c.save()
    return buf.getvalue()


# ── Plantillas ───────────────────────────────────────────────────────────────

def _flc_60h(rng, horas=60, **_):
    nombre, apellidos, dni = persona(rng)
    fin = fecha(rng)
    registro = f"{rng.integers(100000, 999999)}/{rng.integers(100000, 999999)}/{rng.integers(1000000, 9999999)}"
    curso = f"{rng.integers(10**10, 10**11 - 1)}MAD"
    entidad = f"FORMACION PREVENTIVA {rng.choice(['NORTE', 'SUR', 'CENTRO'])} SL"
    verdad = {"titular": f"{apellidos}, {nombre}", "nif": dni, "horas": horas, "numero_registro": registro,
              "numero_curso": curso, "fecha": fin}

    def dibujar(h, _):
        h.orla()
        h.texto(h.ancho / 2, 32, "PREVENCIÓN DE RIESGOS LABORALES", 20, True, True, (0.2, 0.3, 0.55))
        h.texto(h.ancho / 2, 50, f"D./Dña. {apellidos}, {nombre} con NIF {dni} y nº de registro {registro}", 12, centro=True)
        h.texto(h.ancho / 2, 62, "Ha asistido con pleno aprovechamiento al curso de", 12, centro=True)
        h.texto(h.ancho / 2, 74, f"{horas}H NIVEL BÁSICO DE PREVENCIÓN EN CONSTRUCCIÓN", 15, True, True)
        h.parrafo(25, 88, "Según Convenio General del sector de la Construcción, que regula la formación de los "
                               f"trabajadores/as de este sector, se ha celebrado por parte de {entidad}, la jornada "
                               f"formativa impartida con carácter presencial y duración de {horas},00 horas, siendo el "
                               f"calendario de clases: del {en_letra(fin - timedelta(days=14))} al {en_letra(fin)}.",
                      h.ancho - 50, 10.5)
        h.texto(40, 150, "Firma y sello del centro formador", 9)
        h.texto(h.ancho - 90, 150, "Firma trabajador/a", 9)
        h.firma(45, 165, rng)
        h.parrafo(25, 182, "Entidad homologada por la Fundación Laboral de la Construcción con el número de registro "
                           f"0{rng.integers(100000000, 999999999)} y número de curso {curso}", h.ancho - 50, 8)
    return _pdf(dibujar, apaisado=True), verdad


def _ts_riesgos(rng, titulo="Técnico Superior en Prevención de Riesgos Profesionales", **_):
    nombre, apellidos, dni = persona(rng)
    expedicion = fecha(rng, 400, 6000)
    registro = str(rng.integers(10**11, 10**12 - 1))
    verdad = {"titular": f"{nombre} {apellidos}", "nif": dni, "fecha": expedicion, "numero_registro": registro,
              "titulo": titulo.upper().replace("É", "E").replace("Ó", "O")}

    def dibujar(h, _):
        h.orla()
        h.texto(h.ancho / 2, 30, "Felipe VI, Rey de España", 18, True, True, (0.2, 0.3, 0.55))
        h.texto(h.ancho / 2, 44, "y en su nombre", 10, centro=True)
        h.texto(h.ancho / 2, 52, "La Consejera de Educación de la Comunidad de Madrid", 14, True, True)
        h.texto(h.ancho / 2, 61, "Considerando que, conforme a las disposiciones y circunstancias prevenidas por la legislación vigente,", 9.5, centro=True)
        h.texto(h.ancho / 2, 75, f"Don {nombre.title()} {apellidos.title()}", 20, True, True)
        y = h.parrafo(35, 86, f"nacido el día {en_letra(date(1985, 5, 3))} en Madrid, de nacionalidad española, con DNI "
                               f"{dni[:2]}.{dni[2:5]}.{dni[5:8]}-{dni[8]}, ha superado los estudios de Formación Profesional "
                               f"regulados en el Real Decreto 1161/2001, con la calificación de 7,5, expide a su favor, el presente",
                      h.ancho - 70, 10, centro=True)
        h.texto(h.ancho / 2, y + 8, f"Título de {titulo}", 15, True, True)
        h.texto(h.ancho / 2, y + 20, "con carácter oficial y validez en todo el territorio español.", 10, centro=True)
        h.texto(h.ancho / 2, y + 30, f"Madrid, a {en_letra(expedicion)}", 11, centro=True)
        h.texto(40, 180, "CM-A-" + registro[:6], 9)
        h.texto(h.ancho / 2 - 20, 176, "Registro Autonómico de Títulos", 8)
        h.texto(h.ancho / 2 - 15, 181, registro, 9)
    return _pdf(dibujar, apaisado=True), verdad


def _ts_prl(rng, oficial=True, **_):
    nombre, apellidos, dni = persona(rng)
    expedicion = fecha(rng, 200, 3000)
    rnt = f"{expedicion.year}/{rng.integers(100000, 999999)}"
    universidad = f"Universidad de {rng.choice(['Ejemplo', 'Villaficticia', 'Pruebas'])}"
    titulo = ("Máster Universitario en Prevención de Riesgos Laborales" if oficial
              else "Máster en Prevención de Riesgos Laborales (Título Propio)")
    verdad = {"titular": f"{nombre} {apellidos}", "fecha": expedicion, "numero_registro": rnt if oficial else None,
              "universidad": universidad.upper(), "titulo_oficial": oficial}

    def dibujar(h, _):
        h.orla()
        h.texto(h.ancho / 2, 28, "Felipe VI, Rey de España" if oficial else universidad, 18, True, True, (0.2, 0.3, 0.55))
        h.texto(h.ancho / 2, 40, "y en su nombre el" if oficial else "", 10, centro=True)
        h.texto(h.ancho / 2, 48, f"Rector de la {universidad}", 14, True, True)
        h.texto(h.ancho / 2, 58, "Considerando que, conforme a las disposiciones y circunstancias previstas por la legislación vigente,", 9.5, centro=True)
        h.texto(h.ancho / 2, 72, f"Doña {nombre.title()} {apellidos.title()}", 20, True, True)
        h.texto(h.ancho / 2, 82, f"nacida el día {en_letra(date(1981, 2, 7))} en Madrid, de nacionalidad española,", 10, centro=True)
        h.texto(h.ancho / 2, 89, "ha superado los estudios conducentes al título " + ("oficial de" if oficial else "propio de"), 10, centro=True)
        h.texto(h.ancho / 2, 101, titulo, 15, True, True)
        h.texto(h.ancho / 2, 110, f"por la {universidad}", 11, centro=True)
        if oficial:
            h.texto(h.ancho / 2, 118, "expide el presente título oficial con validez en todo el territorio nacional.", 10, centro=True)
        h.texto(h.ancho / 2, 130, f"Dado en Madrid, a {en_letra(expedicion)}", 11, centro=True)
        if oficial:
            h.texto(40, 176, "Registro Nacional de Títulos", 8)
            h.texto(40, 181, rnt, 9)
    return _pdf(dibujar, apaisado=True), verdad


def _certificado(rng, emisor: str, **kw):
    razon = f"{rng.choice(EMPRESAS)} SL"
    ident = cif(rng)
    emision = fecha(rng, kw.get("antiguedad_min", 5), kw.get("antiguedad_max", 60))
    codigo = "".join(rng.choice(list("ABCDEFGHJKLMNPQRSTUVWXYZ23456789"), 16))
    al_corriente = kw.get("al_corriente", True)
    verdad = {"razon_social": razon, "identificador": ident, "fecha_emision": emision, "al_corriente": al_corriente,
              "codigo_verificacion": codigo}
    tgss = emisor == "tgss"

    def dibujar(h, _):
        if tgss:
            h.texto(20, 22, "MINISTERIO DE INCLUSIÓN, SEGURIDAD SOCIAL Y MIGRACIONES", 9, True)
            h.texto(20, 27, "TESORERÍA GENERAL DE LA SEGURIDAD SOCIAL", 9, True)
            h.texto(h.ancho / 2, 50, "CERTIFICADO DE ESTAR AL CORRIENTE EN LAS OBLIGACIONES DE SEGURIDAD SOCIAL", 11, True, True)
        else:
            h.texto(20, 22, "Agencia Tributaria", 12, True)
            h.texto(h.ancho / 2, 50, "CERTIFICADO DE ESTAR AL CORRIENTE DE OBLIGACIONES TRIBUTARIAS", 11, True, True)
        h.texto(25, 68, "Razón social:", 10, True)
        h.texto(60, 68, razon, 10)
        h.texto(25, 75, "CIF:", 10, True)
        h.texto(60, 75, ident, 10)
        cuerpo = ("La Tesorería General de la Seguridad Social CERTIFICA: Que según los antecedentes obrantes en este "
                  "Servicio Común, la empresa arriba indicada " if tgss else
                  "La Agencia Estatal de Administración Tributaria CERTIFICA: Que conforme a los datos que obran en esta "
                  "Agencia, el solicitante arriba indicado ")
        cuerpo += ("está al corriente en el pago de sus obligaciones." if al_corriente
                   else "no está al corriente en el pago de sus obligaciones.")
        y = h.parrafo(25, 90, cuerpo, h.ancho - 50, 10.5)
        if "validez" in kw:
            y = h.parrafo(25, y + 4, f"El presente certificado tiene una validez de {kw['validez']} meses desde su expedición.", h.ancho - 50, 10)
        h.texto(25, y + 12, f"Fecha de emisión: {num(emision)}", 10)
        h.texto(25, 270, f"Código Seguro de Verificación (CSV): {codigo}", 8)
    return _pdf(dibujar), verdad


def _certificado_tgss(rng, **kw):
    return _certificado(rng, "tgss", **kw)


def _certificado_aeat(rng, **kw):
    return _certificado(rng, "aeat", **kw)


def _seguro_rc(rng, vigente=True, **_):
    tomador = f"{rng.choice(EMPRESAS)} SL"
    ident = cif(rng)
    ident_aseguradora = cif(rng)
    poliza = f"RC-{rng.integers(1000000, 9999999)}"
    desde = fecha(rng, 30, 200) if vigente else fecha(rng, 500, 800)
    hasta = date(desde.year + 1, desde.month, min(desde.day, 28))
    limite = 600000
    verdad = {"tomador": tomador, "identificador": ident, "poliza": poliza, "vigencia_desde": desde,
              "vigencia_hasta": hasta, "limite_siniestro": float(limite)}

    def dibujar(h, _):
        h.texto(20, 20, "SEGUROS FICTICIOS, S.A.", 13, True, color=(0.1, 0.3, 0.5))
        h.texto(20, 25, f"CIF {ident_aseguradora} - Compañía de seguros y reaseguros", 8)
        h.texto(h.ancho / 2, 42, "PÓLIZA DE SEGURO DE RESPONSABILIDAD CIVIL GENERAL", 12, True, True)
        h.texto(h.ancho / 2, 48, "CONDICIONES PARTICULARES", 10, True, True)
        h.campo(20, 60, 80, "Nº DE PÓLIZA", poliza)
        h.campo(110, 60, 80, "ENTIDAD ASEGURADORA", "SEGUROS FICTICIOS, S.A.")
        h.campo(20, 76, 120, "TOMADOR DEL SEGURO", tomador)
        h.campo(150, 76, 40, "CIF", ident)
        h.parrafo(20, 96, f"Duración del seguro: desde las 00:00 horas del {num(desde)} hasta las 24:00 horas del {num(hasta)}.",
                  h.ancho - 40, 10)
        h.texto(20, 110, f"Límite por siniestro: {limite:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."), 10)
        h.texto(20, 117, "Prima total anual: 1.250,00 €", 10)
        h.parrafo(20, 130, "El asegurador garantiza el pago de las indemnizaciones de las que el asegurado sea civilmente "
                           "responsable por daños causados a terceros en el ejercicio de su actividad de construcción.",
                  h.ancho - 40, 9.5)
    return _pdf(dibujar), verdad


def _registro_empresa(rng, **_):
    razon = f"{rng.choice(EMPRESAS)} SL"
    ident = cif(rng)
    numero = f"{rng.integers(10, 52):02d}/{rng.integers(10, 52):02d}/{rng.integers(1000000, 9999999)}"
    alta = fecha(rng, 100, 2000)
    verdad = {"razon_social": razon, "identificador": ident, "numero_inscripcion": numero, "fecha": alta}

    def dibujar(h, _):
        h.texto(h.ancho / 2, 35, "REGISTRO DE EMPRESAS ACREDITADAS", 14, True, True)
        h.texto(h.ancho / 2, 42, "Ley 32/2006, reguladora de la subcontratación en el Sector de la Construcción", 9, centro=True)
        h.texto(h.ancho / 2, 58, "CERTIFICADO DE INSCRIPCIÓN", 12, True, True)
        h.campo(25, 72, 110, "RAZÓN SOCIAL", razon)
        h.campo(145, 72, 40, "CIF", ident)
        h.campo(25, 88, 80, "Nº DE INSCRIPCIÓN", numero)
        h.campo(115, 88, 70, "FECHA DE INSCRIPCIÓN", num(alta))
        h.parrafo(25, 108, "La empresa arriba indicada figura inscrita en el Registro de Empresas Acreditadas del sector "
                           "de la construcción de esta Comunidad Autónoma.", h.ancho - 50, 10)
    return _pdf(dibujar), verdad


def _apertura_centro_trabajo(rng, **_):
    razon = f"{rng.choice(EMPRESAS)} SL"
    ident = cif(rng)
    inicio = fecha(rng, 5, 200)
    direccion = f"CALLE FICTICIA {rng.integers(1, 99)}, MADRID"
    verdad = {"razon_social": razon, "identificador": ident, "direccion_obra": direccion, "fecha": inicio}

    def dibujar(h, _):
        h.texto(h.ancho / 2, 30, "COMUNICACIÓN DE APERTURA O REANUDACIÓN DE ACTIVIDAD", 12, True, True)
        h.texto(h.ancho / 2, 36, "EN CENTROS DE TRABAJO (Orden TIN/1071/2010) - OBRAS DE CONSTRUCCIÓN", 9, centro=True)
        h.texto(20, 50, "DATOS DE LA EMPRESA", 10, True)
        h.campo(20, 56, 120, "NOMBRE O RAZÓN SOCIAL", razon)
        h.campo(150, 56, 40, "CIF/NIF", ident)
        h.texto(20, 76, "DATOS DEL CENTRO DE TRABAJO", 10, True)
        h.campo(20, 82, 170, "DIRECCIÓN DE LA OBRA", direccion)
        h.campo(20, 98, 60, "FECHA DE INICIO", num(inicio))
        h.parrafo(20, 118, "La empresa comunica a la autoridad laboral la apertura del centro de trabajo indicado.",
                  h.ancho - 40, 10)
    return _pdf(dibujar), verdad


def _documento_libre(titulo: str, cuerpo: str):
    def generar_libre(rng, **_):
        razon = f"{rng.choice(EMPRESAS)} SL"
        ident = cif(rng)
        f = fecha(rng, 10, 300)
        verdad = {"razon_social": razon, "identificador": ident, "fecha": f}

        def dibujar(h, i):
            if i == 0:
                h.texto(h.ancho / 2, 40, titulo, 16, True, True)
                h.campo(30, 60, 110, "EMPRESA", razon)
                h.campo(150, 60, 35, "CIF", ident)
                h.campo(30, 76, 50, "FECHA", num(f))
            y = h.parrafo(25, 100 if i == 0 else 30, cuerpo, h.ancho - 50, 10)
            h.parrafo(25, y + 6, cuerpo, h.ancho - 50, 10)
        return _pdf(dibujar, paginas=2), verdad
    return generar_libre


def _contrato_laboral(rng, **_):
    razon = f"{rng.choice(EMPRESAS)} SL"
    ident = cif(rng)
    _, representante, dni_rep = persona(rng)
    nombre, apellidos, dni = persona(rng)
    inicio = fecha(rng, 5, 400)
    verdad = {"identificador_empresa": ident, "razon_social": razon, "nif_trabajador": dni,
              "nombre_trabajador": f"{nombre} {apellidos}", "fecha_inicio": inicio, "tipo_contrato": "INDEFINIDO"}

    def dibujar(h, i):
        if i == 0:
            h.texto(h.ancho / 2, 20, "CONTRATO DE TRABAJO INDEFINIDO", 14, True, True)
            h.texto(15, 32, "DATOS DE LA EMPRESA", 10, True)
            h.campo(15, 38, 60, "CIF/NIF/NIE", ident)
            h.campo(15, 52, 130, "D./DÑA.", f"JUAN {representante}")
            h.campo(150, 52, 45, "NIF/NIE", dni_rep)
            h.campo(15, 66, 180, "NOMBRE O RAZÓN SOCIAL DE LA EMPRESA", razon)
            h.campo(15, 80, 180, "DOMICILIO SOCIAL", "CALLE INVENTADA 1")
            h.texto(15, 100, "DATOS DE LA PERSONA TRABAJADORA", 10, True)
            h.campo(15, 106, 130, "D./DÑA.", f"{nombre} {apellidos}")
            h.campo(150, 106, 45, "NIF/NIE", dni)
            h.campo(15, 120, 50, "FECHA NACIMIENTO (dd/mm/aaaa)", "12/05/1990")
            h.campo(70, 120, 60, "NACIONALIDAD", "ESPAÑOLA")
            h.campo(15, 134, 80, "NIVEL FORMATIVO", "BACHILLERATO")
            h.texto(15, 154, "DATOS DE LA ASISTENCIA LEGAL (EN SU CASO)", 10, True)
        else:
            h.texto(h.ancho / 2, 20, "CLÁUSULAS", 12, True, True)
            h.parrafo(15, 32, "PRIMERA: el/la trabajador/a prestará sus servicios como recurso preventivo.", h.ancho - 30)
            h.parrafo(15, 44, "CUARTA: la duración del presente contrato será INDEFINIDA, iniciándose la relación laboral "
                              f"en fecha {num(inicio)} y se establece un período de prueba de dos meses.", h.ancho - 30)
            h.parrafo(15, 60, "En lo no previsto en este contrato se estará a lo dispuesto en el Estatuto de los Trabajadores.",
                      h.ancho - 30)
    return _pdf(dibujar, paginas=2), verdad


def _reconocimiento_medico(rng, resultado="APTO", **_):
    _, _, dni = persona(rng)
    f = fecha(rng, 10, 300)
    verdad = {"nif": dni, "fecha": f, "apto": resultado}

    def dibujar(h, _):
        h.texto(20, 20, "SERVICIO DE PREVENCIÓN - VIGILANCIA DE LA SALUD", 10, True)
        h.texto(h.ancho / 2, 40, "CERTIFICADO DE APTITUD", 14, True, True)
        h.texto(h.ancho / 2, 47, "Reconocimiento médico (artículo 22 de la Ley 31/1995)", 9, centro=True)
        h.campo(25, 62, 60, "NIF DEL TRABAJADOR", dni)
        h.campo(95, 62, 50, "FECHA DEL RECONOCIMIENTO", num(f))
        h.campo(25, 80, 100, "PUESTO DE TRABAJO", "RECURSO PREVENTIVO EN OBRA")
        h.texto(25, 102, f"RESULTADO: {resultado}", 12, True)
        h.parrafo(25, 115, "Observaciones clínicas confidenciales: texto de prueba que no debe salir en la respuesta.",
                  h.ancho - 50, 9)
        h.texto(120, 150, "Fdo. El médico del trabajo", 9)
    return _pdf(dibujar), verdad


def _ficha(titulo: str, ley: str, cuerpo: str):
    def generar_ficha(rng, firmada=True, **_):
        nombre, apellidos, dni = persona(rng)
        f = fecha(rng, 5, 300)
        verdad = {"nif_trabajador": dni, "nombre_trabajador": f"{nombre} {apellidos}", "fecha": f, "firmado": firmada}

        def dibujar(h, _):
            h.texto(h.ancho / 2, 25, titulo, 13, True, True)
            h.texto(h.ancho / 2, 32, ley, 9, centro=True)
            h.campo(20, 46, 120, "NOMBRE Y APELLIDOS", f"{nombre} {apellidos}")
            h.campo(150, 46, 40, "NIF", dni)
            h.campo(20, 62, 60, "PUESTO", "RECURSO PREVENTIVO")
            y = h.parrafo(20, 82, cuerpo, h.ancho - 40, 10)
            h.texto(20, y + 10, f"Fecha: {num(f)}", 10)
            h.texto(20, y + 22, "Firma del trabajador:", 10, True)
            if firmada:
                h.firma(25, y + 34, rng)
            h.texto(120, y + 22, "Firma de la empresa:", 10, True)
            h.firma(125, y + 34, rng)
        return _pdf(dibujar), verdad
    return generar_ficha


PLANTILLAS = {
    "flc_60h": _flc_60h,
    "ts_riesgos": _ts_riesgos,
    "ts_prl": _ts_prl,
    "certificado_tgss": _certificado_tgss,
    "certificado_aeat": _certificado_aeat,
    "seguro_rc": _seguro_rc,
    "registro_empresa": _registro_empresa,
    "apertura_centro_trabajo": _apertura_centro_trabajo,
    "plan_seguridad_salud": _documento_libre(
        "PLAN DE SEGURIDAD Y SALUD EN EL TRABAJO",
        "Plan de seguridad y salud de la obra elaborado por el contratista en aplicación del estudio de seguridad, "
        "conforme al Real Decreto 1627/1997. Recoge la identificación de riesgos, las medidas preventivas y la "
        "organización de los recursos preventivos y del coordinador en la obra."),
    "evaluacion_riesgos": _documento_libre(
        "EVALUACIÓN DE RIESGOS LABORALES",
        "Evaluación de riesgos de los puestos de trabajo según el artículo 16 de la Ley 31/1995. Para cada riesgo se "
        "estima la probabilidad y la severidad de las consecuencias y se proponen medidas preventivas."),
    "cae_documentacion": _documento_libre(
        "COORDINACIÓN DE ACTIVIDADES EMPRESARIALES",
        "Documentación de coordinación de actividades empresariales conforme al Real Decreto 171/2004 en los casos de "
        "concurrencia de trabajadores de varias empresas en un mismo centro de trabajo. La empresa titular informa de "
        "los riesgos propios del centro."),
    "contrato_laboral": _contrato_laboral,
    "reconocimiento_medico": _reconocimiento_medico,
    "informacion_art18": _ficha(
        "REGISTRO DE INFORMACIÓN DE RIESGOS AL TRABAJADOR", "Artículo 18 de la Ley 31/1995 de Prevención de Riesgos Laborales",
        "El trabajador declara haber recibido información sobre los riesgos del puesto de trabajo, las medidas de "
        "protección y prevención aplicables y las medidas de emergencia."),
    "formacion_art19": _ficha(
        "REGISTRO DE FORMACIÓN EN PREVENCIÓN DE RIESGOS LABORALES", "Artículo 19 de la Ley 31/1995",
        "El trabajador ha recibido formación teórica y práctica, suficiente y adecuada, en materia preventiva, con una "
        "duración de 8 horas. Contenido: riesgos del puesto, medidas preventivas y emergencias."),
    "entrega_epis": _ficha(
        "REGISTRO DE ENTREGA DE EQUIPOS DE PROTECCIÓN INDIVIDUAL (EPI)", "Real Decreto 773/1997",
        "Recibí los siguientes EPIs: casco de seguridad (marca Ejemplo, modelo X1, talla única), botas de seguridad "
        "(talla 42) y arnés anticaídas, y me comprometo a utilizarlos correctamente."),
}


# Campos que están en la página 2 (una foto de la primera página no puede tenerlos).
CAMPOS_PAGINA_2 = {"contrato_laboral": ("fecha_inicio",)}


def generar(tipo: str, rng: np.random.Generator | None = None, **opciones) -> tuple[bytes, dict]:
    """PDF digital del tipo y la verdad de sus campos (fechas como `date`)."""
    return PLANTILLAS[tipo](rng or np.random.default_rng(0), **opciones)


# ── Escaneos y fotos ─────────────────────────────────────────────────────────

def a_imagen(pdf: bytes, ppp: int = 200, pagina: int = 0) -> np.ndarray:
    from .pdf import renderizar
    return renderizar(pdf, pagina, ppp)


def escaneo(img: np.ndarray, rng: np.random.Generator, giro_max: float = 1.2) -> np.ndarray:
    """Escáner o fotocopia: gris, un poco torcido, ruido y compresión."""
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gris.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), float(rng.uniform(-giro_max, giro_max)), 1.0)
    gris = cv2.warpAffine(gris, m, (w, h), borderValue=255)
    gris = cv2.GaussianBlur(gris, (3, 3), 0.6)
    gris = np.clip(gris + rng.normal(0, 6, gris.shape), 0, 255).astype(np.uint8)
    return sintetico.jpeg(cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR), 75)


def foto(img: np.ndarray, rng: np.random.Generator, fuerza: float = 1.0) -> np.ndarray:
    """Foto de móvil de la hoja sobre una mesa: perspectiva, luz desigual, sombra y compresión."""
    h, w = img.shape[:2]
    margen = int(max(h, w) * 0.12)
    mesa = np.full((h + 2 * margen, w + 2 * margen, 3), (70, 85, 100), np.uint8)
    mesa = sintetico.ruido(mesa, rng, 10)
    mesa[margen:margen + h, margen:margen + w] = img
    salida = sintetico.perspectiva(mesa, rng, 0.05 * fuerza)
    salida = sintetico.degradado_luz(salida, rng)
    if fuerza >= 1:
        salida = sintetico.sombra(salida, rng)
    return sintetico.jpeg(salida, 80)


def pdf_de_imagen(img: np.ndarray | list[np.ndarray], ppp: int = 200) -> bytes:
    """PDF escaneado (solo imagen, sin capa de texto), como «Imprimir a PDF» de una foto."""
    from PIL import Image
    imagenes = [Image.fromarray(cv2.cvtColor(i, cv2.COLOR_BGR2RGB)) for i in (img if isinstance(img, list) else [img])]
    buf = io.BytesIO()
    imagenes[0].save(buf, format="PDF", resolution=ppp, save_all=True, append_images=imagenes[1:])
    return buf.getvalue()


def num_paginas(pdf: bytes) -> int:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf)
    try:
        return len(doc)
    finally:
        doc.close()


def escanear(pdf: bytes, rng: np.random.Generator, ppp: int = 200) -> bytes:
    """El PDF digital impreso y escaneado: todas sus páginas, como imagen."""
    return pdf_de_imagen([escaneo(a_imagen(pdf, ppp, i), rng) for i in range(num_paginas(pdf))], ppp)


def a_jpeg(img: np.ndarray, calidad: int = 88) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, calidad])[1].tobytes()
