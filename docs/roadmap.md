# Roadmap: OCR local para todos los documentos

Plan de desarrollo para llevar el OCR del DNI a **todos los tipos de documento** (titulaciones,
certificados, pólizas, contratos, fichas firmadas…), con sus pruebas, y sustituir por completo un
OCR en la nube. Diseño general en [OCR local multi-documento](ocr-multidocumento.md).

**Estado (01/10/2026):** hitos H1–H5 implementados y probados (16 tipos de documento). Falta sobre
todo medir y calibrar con **documentos reales** de cada tipo (§5) y lo que depende de quien llama
(H6). Resultados de la medición en [§0](#0-estado-y-resultados).

## Reglas

- **Todo en localhost.** El servicio escucha solo en `127.0.0.1` (o en la red interna de Docker
  del mismo servidor). No se publica como API en internet, no tiene subdominio y ningún documento
  sale de la máquina.
- **Sin nube y sin telemetría.** Solo motores locales (Tesseract, RapidOCR); las pruebas de CI se
  ejecutan con la red del contenedor cortada.
- **Sin estado y sin guardar nada.** Los bytes llegan en la petición, se procesan en memoria (sin
  ficheros temporales) y se descartan. Los logs solo llevan tipo, resultado y tiempo (y las
  librerías de PDF, que en DEBUG vuelcan el texto, nunca bajan de WARNING).
- **El OCR lee; no decide.** Devuelve qué pone el documento y si es coherente consigo mismo
  (letra del NIF, fechas, horas, firma…). Comparar con los datos del usuario y aceptar o rechazar
  es cosa de quien llama.
- **Métrica que manda: 0 datos erróneos dados por buenos.** Mejor pedir otra foto o pasar a
  revisión manual que inventar un dato.
- **Licencias permisivas.** Nada AGPL/GPL en el servicio (por eso no PyMuPDF; el modelo `mrz` de
  Tesseract sigue desactivado en la imagen de producción).

---

## 0. Estado y resultados

| Hito | Estado |
|---|---|
| H1 Núcleo de documentos | ✔ Hecho |
| H2 Titulaciones de prevención | ✔ Hecho · probado con 3 títulos reales |
| H3 Clasificador y fotos de documentos A4 | ✔ Hecho · falta calibrar con fotos reales |
| H4 Documentos de empresa | ✔ Hecho · probado con 14 certificados reales publicados en internet (TGSS, AEAT, REA, RC) |
| H5 Documentos de prevención del trabajador | ✔ Hecho · probado con 2 modelos oficiales rellenados |
| H6 Sustituir el OCR en la nube | Depende de quien llama (el servicio ya está listo) |

### Medición (`python -m herramientas.medir`)

Con 2 CPU (el límite del contenedor), 01/10/2026:

| Lote | Docs | COMPLETA | Campos erróneos dados por buenos | Tiempo por documento (mediana / p95) |
|---|---|---|---|---|
| Sintéticos, PDF digital (16 tipos × 2) | 32 | 32 (100 %) | **0** | 0,06 s / 0,20 s |
| Sintéticos, escaneados | 32 | 31 (97 %) | **1**⁴ | 3,8 s / 9,7 s⁵ |
| Sintéticos, foto de móvil | 32 | 26 (81 %)¹ | **0** | 4,6 s / 7,4 s |
| Títulos reales (diploma FLC digital, FP fotografiado, máster escaneado) | 3 | 3 · 18/18 campos | **0** | 0,7 s digital; 17–24 s escaneado² |
| Modelos oficiales rellenados (contrato del SEPE, registro de EPI) en formulario, aplanado y escaneado | 12 | 5³ | **0** | 1,3 s digital; 17 s escaneado² |
| Certificados reales publicados por sus titulares (7 TGSS, 1 AEAT, 4 REA, 2 RC), PDF digital | 14 | 9⁶ | **0** | 0,14 s / 0,43 s |

1. Las 2 fotos del contrato no pueden estar completas: la fecha de inicio está en la página 2.
   Sin ellas, 26/30 (87 %). Los que no salen COMPLETA quedan INCOMPLETA o ILEGIBLE, nunca con un
   dato erróneo.
2. Varias páginas por OCR (el contrato del SEPE tiene 20; como mucho 5 pasan por OCR) o fotos de
   títulos enmarcados con reflejos, que necesitan los dos motores.
3. En los registros de EPI escaneados no se puede asegurar si están firmados (queda INCOMPLETA).
4. Un CIF «B…» leído «G…» en un REA escaneado: el dígito de control del CIF no distingue esas
   letras. Apareció al poner en la plantilla sintética del REA el bloque del solicitante (como en
   el modelo real), que mueve la maqueta. Pendiente: exigir que los dos motores lean lo mismo.
5. Parte de los escaneados se midió a la vez que otros lotes: el p95 real es algo menor.
6. INCOMPLETA: 3 TGSS del modelo antiguo («NO tiene pendiente de ingreso ninguna reclamación…»
   no se reconoce como «al corriente») y las 2 pólizas (tomador mal leído, sin darse por bueno).

Pruebas: 282 rápidas + 33 con OCR real; en CI se ejecutan sin red. Falla
`test_foto_sin_datos_erroneos[seguro_rc]` desde el 01/10/2026 (los sintéticos usan la fecha de
hoy): en la foto, el tomador sale con el nombre de la aseguradora y se da por bueno.

### Cambios respecto al plan inicial (aprendido al construirlo)

- **Cuarto estado de lectura: `OTRO_DOCUMENTO`.** Cuando el clasificador ve claramente otro tipo
  (un diploma subido como máster), se dice así en vez de «incompleto».
- **PDF con PDFium, no con pdfplumber.** Leer las 20 páginas del contrato oficial del SEPE tardaba
  8,4 s con pdfplumber y 0,16 s con PDFium. pdfplumber queda solo para los valores de formularios
  sin aplanar (que viven en anotaciones).
- **Límite de páginas por tipo.** El modelo oficial de contrato tiene 20 páginas (instrucciones de
  todas sus variantes): 5 por defecto, 25 en contratos, 60 en documentos libres. Como mucho 5
  páginas pasan por OCR.
- **Dos motores combinados en vez de elegir uno por tipo.** Tesseract respeta espacios, tildes y
  Ñ, pero en fotos con reflejos se deja trozos de página; RapidOCR encuentra casi todas las líneas
  pero pega palabras («conDNI1.234.567-L») y no conoce la Ñ. En fotos: RapidOCR detecta las líneas,
  Tesseract las reconoce (todas en una sola llamada, con el contraste normalizado por línea) y
  RapidOCR relee solo las dudosas. En escaneos limpios basta Tesseract.
- **Confusiones típicas del OCR en identificadores** (B↔8, D↔0): se corrigen solo en la posición
  de la letra y solo si el dígito o letra de control lo confirma, y solo junto a su etiqueta.
- **Sin Augraphy.** Las degradaciones de escaneo y foto se hacen con las de `sintetico.py`
  (perspectiva, luz, sombra, ruido, JPEG): una dependencia menos.
- **FLC: el «número de curso» no identifica a la persona.** Lo comparten todos los alumnos del
  curso; el identificador del alumno es el «nº de registro» (`NNNNNN/NNNNNN/NNNNNNN`). Para
  detectar un diploma usado por dos personas hay que usar el nº de registro.
- **El CSV no tiene dígito de control.** Si sale del OCR, solo se devuelve si los dos motores leen
  el mismo código; si no, se omite con un aviso (en fotos, un «5» leído como «S» daba un código
  erróneo).
- **Fechas que no son del documento.** Se excluyen la de nacimiento y las del propio modelo de
  formulario («Fecha aprobación», «Revisión», «Versión»). Si hay etiqueta de expedición pero su
  fecha es ilegible, el campo queda vacío en vez de coger otra fecha.
- **REA: el certificado estatal trae dos identificadores.** Arriba, «Datos de la solicitud» con el
  nombre y el NIF de quien lo pide; tras «CERTIFICA», la empresa. Con certificados reales
  publicados en internet se devolvía el NIF del solicitante como CIF de la empresa (3 de 3). Ahora
  la empresa se busca solo tras «CERTIFICA»; si el OCR pierde esas cabeceras y hay más de un
  identificador en el texto, el campo queda vacío. La fecha es la de inscripción («desde el …»),
  no la de la solicitud. También se lee el nº del modelo de Madrid («Núm. REA: 12 28 0098249»).
- **Fichas con dos personas.** En los modelos reales el primer «D./Dª.» suele ser quien entrega o
  informa; el trabajador se busca por sus etiquetas («entrega a», «persona que se incorpora»…) y la
  firma se mide junto a la etiqueta del trabajador, sin contar trazos que invaden desde la fila de
  arriba.

### Siguiente

1. **Lote real por tipo** (§5): hoy hay 3 títulos reales, 2 modelos oficiales rellenados con
   datos ficticios y 14 certificados de empresa publicados (TGSS, AEAT, REA, RC). Faltan
   aperturas, contratos, reconocimientos y fichas reales; y escaneos y fotos de móvil de todos.
2. **Arreglos pendientes del lote de internet:** RC (tomador y aseguradora mal leídos; falla la
   prueba de la foto sintética), TGSS del modelo antiguo («al corriente» y código CEA),
   certificados de agencias tributarias autonómicas tomados por AEAT, y CIF «B»/«G» en escaneos.
3. **Calibrar** los umbrales de calidad de documentos (`umbrales.yaml → documento`) con esas fotos.
4. **Tiempo en fotos** (mediana 4,6 s y p95 7,4 s con 2 CPU): bajar el p95 por debajo de 6 s.
5. **Cadena de confianza de las firmas** sin conexión: incluir en la imagen las raíces de
   confianza (FNMT, sedes de la Administración) para pasar de «íntegra» a «de confianza».
6. **Plantillas de posiciones por emisor** (como la del anverso del DNI) para los formatos fijos
   más frecuentes (diploma FLC), para leer por posición cuando el OCR no encuentra la etiqueta.
7. Datasets públicos (MIDV-2020 para el DNI; XFUND español para formularios) aún sin usar.

---

## 1. Contrato común

### Endpoints (en `http://127.0.0.1:8001`)

| Método | Ruta | Qué hace | Estado |
|---|---|---|---|
| `GET` | `/health` | Estado del servicio, motores y nº de tipos | ✔ |
| `POST` | `/v1/dni/verificar` | Flujo completo del DNI | ✔ |
| `GET` | `/v1/documentos/tipos` | Tipos admitidos, sus campos y obligatorios | ✔ |
| `POST` | `/v1/documentos/{tipo}/extraer` | Lee un documento del tipo indicado | ✔ |
| `POST` | `/v1/documentos/clasificar` | Dice qué tipo de documento es | ✔ |

Contrato completo en [openapi.json](openapi.json) y un ejemplo de respuesta por tipo en
[ejemplos/](ejemplos/) (se regeneran con `python -m herramientas.contrato`; un test falla si no
coinciden con el servicio). Detalle de la respuesta en [servicio/README.md](../servicio/README.md).

- `lectura`: `COMPLETA` (todos los campos obligatorios) · `INCOMPLETA` (faltan campos con buena
  calidad → revisión manual) · `ILEGIBLE` (mala calidad → pedir otra foto o escaneo) ·
  `OTRO_DOCUMENTO` (se ha subido otro tipo de documento).
- `origen`: `pdf_digital` · `pdf_escaneado` · `pdf_mixto` · `imagen`. Cada campo lleva el suyo
  (`capa_texto`, `formulario`, `ocr:tesseract`, `ocr:rapidocr`, `calculado`…).
- `autenticidad`: `firmas` (PAdES: `integra`, `cubre_todo`, `modificado_tras_firmar`, `firmante`),
  `codigos_verificacion` (CSV/CEA), `qr` y `avisos` (editores, guardados posteriores).

### Errores

| Código | Cuándo |
|---|---|
| 400 | Fichero vacío, corrupto o PDF cifrado |
| 401 | Falta o no vale `X-Api-Key` |
| 404 | `{tipo}` no existe |
| 413 | Más de 15 MB |
| 415 | Formato no admitido |
| 422 | PDF con más páginas del límite del tipo |
| 503 | Hace falta OCR y no hay motores (un PDF digital sigue funcionando sin ellos) |

### Tres caminos según la entrada

```
                  ┌─ PDF con capa de texto ──► texto + posiciones (PDFium) + formularios ◄ exacto, ≈0,1 s
archivo ─► entrada ┼─ PDF escaneado ─────────► render 300 ppp ─► orientar ─► Tesseract     ◄ ≈3–4 s/página
                  └─ foto de móvil ─────────► hoja ─► enderezar ─► detección RapidOCR
                                                 ─► Tesseract por línea (+ RapidOCR si duda) ◄ ≈5 s
                     mismo extractor por tipo  (recibe líneas: texto + caja + origen + lectura alternativa)
```

Se decide **por página** (hay PDFs mixtos). Además de leer, se buscan pruebas de autenticidad
(firma, CSV, QR, metadatos de edición).

---

## 2. Estructura del código

```
mrzlab/
  documentos.py       # leer (PDF o imagen, por página) y procesar un tipo; estados de lectura
  pdf.py              # PDFium: capa de texto, imágenes, render, metadatos; pdfplumber: formularios
  pagina.py           # hoja en la foto, orientación (Tesseract OSD), inclinación
  ocr_documento.py    # Tesseract de página; híbrido detección RapidOCR + relectura; combinar
  lineas.py           # Linea(texto, caja, pagina, origen, confianza, alternativa)
  validadores.py      # NIF / NIE / CIF (y corrección con control), fechas, importes
  autenticidad.py     # firma PAdES (pyHanko), CSV/CEA confirmados, QR, metadatos
  clasificador.py     # tipo de documento por palabras clave con peso
  calidad.py          # + evaluar_documento (alto de letra, reflejo sobre papel)
  extractores/
    base.py           # Extractor, Campo, buscar, tras_etiqueta, valor_tras, nombres
    comunes.py        # titular, NIF del titular, empresa, razón social, fechas, validez
    firma.py          # ¿firmada? tinta en la zona de firma del trabajador
    titulaciones.py   # flc_60h, ts_riesgos, ts_prl
    empresa.py        # certificados TGSS/AEAT, seguro_rc, registro_empresa, apertura, libres
    trabajador.py     # contrato_laboral, reconocimiento_medico, fichas art. 18/19 y EPI
  sintetico_docs.py   # plantillas con datos ficticios → PDF digital, escaneado y foto
  static/documentos.html   # página del lab
servicio/
  documentos.py       # router /v1/documentos/*
herramientas/
  medir.py            # lote real o sintético + verdad.csv → informe por campo y por origen
  contrato.py         # regenera docs/openapi.json y docs/ejemplos/
  rellenar_formularios.py  # rellena modelos oficiales en blanco con datos ficticios
tests/
  test_validadores.py  test_pdf.py  test_autenticidad.py  test_extractores.py  test_clasificador.py
  test_pagina.py  test_documentos_api.py  test_sintetico_docs.py  test_lab_documentos.py
  test_licencias.py
.github/workflows/tests.yml   # CI: imagen, pruebas sin red, licencias
```

Dependencias nuevas (todas MIT/BSD/Apache): `pypdfium2`, `pdfplumber`, `pyHanko`, `reportlab`
(documentos sintéticos del lab y de los tests). Solo en desarrollo: `pypdf`, `pip-licenses`.

---

## 3. Pruebas

| Nivel | Qué prueba | Datos | ¿En CI? |
|---|---|---|---|
| **U** unitario | `extraer` y `validar` con líneas escritas a mano, sin OCR (cada caso raro visto con documentos reales tiene la suya) | En el test | Sí |
| **D** PDF digital | Los 16 tipos: PDF sintético → campos exactos y COMPLETA | `sintetico_docs.py` | Sí |
| **E** escaneado / foto | Los 16 tipos escaneados y fotografiados con OCR real: nunca un dato erróneo en COMPLETA; ≥ 80 % de escaneados COMPLETA | `sintetico_docs.py` | Sí, `-m ocr` (lento) |
| **N** negativos | Cada tipo procesado como otro, página en blanco, corrupto, cifrado, formato | Sintéticos | Sí |
| **A** API | Contrato, errores, límites, clave, no escribe en disco, logs sin datos, datos de salud | Sintéticos | Sí |
| **R** regresión real | `herramientas/medir.py` con `verdad.csv` | Reales y modelos oficiales, **fuera del repo** | No: a mano |

Además: firma PAdES íntegra / modificada / alterada (certificado generado en el test), CSV, QR,
licencias (nada GPL/AGPL), contrato publicado al día, página del lab.

```bash
python -m pytest -m "not ocr"     # ≈280 pruebas, ≈2 min
python -m pytest -m ocr           # escaneos y fotos con OCR real, varios minutos
```

**Criterio para dar un tipo por bueno (nivel R):** 0 campos erróneos con `lectura = COMPLETA`;
`COMPLETA` en ≥ 95 % de PDF digitales, ≥ 80 % de escaneados, ≥ 60 % de fotos; p95 por página
< 1 s digital y < 6 s con OCR (2 CPU).

---

## 4. Hitos

### H1 — Núcleo de documentos ✔

- [x] Lectura por página: PDF digital (PDFium), formularios sin aplanar, escaneado, mixto, imagen.
- [x] Router `/v1/documentos/*` con límites, errores y la misma privacidad que el DNI.
- [x] `sintetico_docs.py`: plantillas de los 16 tipos → PDF digital, escaneado y foto.
- [x] `herramientas/medir.py` (lote real o sintético) y `herramientas/contrato.py`.
- [x] CI en GitHub Actions: pruebas sin red y licencias.
- [x] Pruebas: entrada (digital sin OCR, escaneado, mixto, formulario, cifrado, corrupto, páginas),
      autenticidad (firma íntegra / modificada / alterada, CSV, QR), validadores, API.

### H2 — Titulaciones de prevención ✔

| Tipo | Campos obligatorios | Validaciones |
|---|---|---|
| `flc_60h` | titular, nif, horas, fecha | NIF válido; horas ≥ 60 **en la frase del curso**; menciona FLC / Convenio; fecha ≤ hoy |
| `ts_riesgos` | titular, nif, titulo, fecha | título **leído** con TÉCNICO SUPERIOR + PREVENCIÓN + RIESGOS |
| `ts_prl` | titular, titulo, universidad, fecha | título con PREVENCIÓN + RIESGOS + LABORALES; `titulo_oficial` leído del texto |

- [x] Extractores por etiqueta, frase y posición; nº de registro del alumno y nº de curso separados.
- [x] Probado con los 3 títulos reales disponibles (diploma FLC digital, FP fotografiado en PDF,
      máster escaneado): todos los campos correctos.
- [ ] Plantilla de posiciones del diploma FLC (formato fijo), para cuando el OCR no lee la etiqueta.

### H3 — Clasificador y fotos de documentos A4 ✔

- [x] `clasificador.py` + `POST /v1/documentos/clasificar`; `OTRO_DOCUMENTO` en `/extraer`.
- [x] `pagina.py`: hoja en la foto, perspectiva, orientación 0/90/180/270, inclinación.
- [x] Calidad para A4 (`umbrales.yaml → documento`): alto de la letra, reflejo sobre el papel (el
      papel blanco no es reflejo), sombras, nitidez.
- [x] Motores combinados (ver «Cambios» en §0) y medición de tamaño de detección y umbral.
- [x] Lab: página `/documentos` con muestras sintéticas, campos, texto por línea y página anotada.
- [ ] Calibrar umbrales con fotos reales; XFUND (formularios escaneados en español).

### H4 — Documentos de empresa ✔

| Tipo | Campos | Validaciones |
|---|---|---|
| `certificado_tgss`, `certificado_aeat` | razón social, identificador, fecha de emisión, al corriente, CSV, caducidad | CIF/NIF válido; vigente (validez del propio documento o 6 meses) |
| `seguro_rc` | tomador, identificador del **tomador**, aseguradora, póliza, vigencia, límite | vigente; fechas coherentes |
| `registro_empresa` | razón social, identificador, nº de inscripción, fecha | identificador válido |
| `apertura_centro_trabajo` | razón social, identificador, dirección de la obra, fecha | identificador válido |
| `plan_seguridad_salud`, `evaluacion_riesgos`, `cae_documentacion` | razón social, identificador, fecha | solo clasificación (texto libre) |

- [ ] Medir con certificados, pólizas, REA y aperturas reales.

### H5 — Documentos de prevención del trabajador ✔

| Tipo | Campos | Nota |
|---|---|---|
| `contrato_laboral` | identificador de la empresa, razón social, NIF y nombre del trabajador, fecha de inicio, tipo | nunca el NIF del representante de la empresa |
| `reconocimiento_medico` | NIF, fecha, apto | **solo** esos campos (datos de salud) |
| `informacion_art18`, `formacion_art19`, `entrega_epis` | NIF y nombre del trabajador, fecha, firmado | firma manuscrita o electrónica |

- [x] Probado con el contrato indefinido oficial del SEPE y un registro de entrega de EPI real,
      rellenados con datos ficticios (`herramientas/rellenar_formularios.py`), en formulario,
      aplanado y escaneado.
- [ ] Medir con reconocimientos y fichas reales.

### H6 — Sustituir el OCR en la nube

Lo hace quien llama al servicio:

1. [ ] **En paralelo:** usar los dos OCR durante 2–4 semanas y comparar solo campos y resultado.
2. [ ] **Cambio por tipo** cuando el local cumple §3 y no es peor en datos erróneos dados por buenos.
3. [ ] **Retirar** el cliente de la nube, sus credenciales y su mención en la política de privacidad.

El servicio ya está preparado: [x] funciona con el contenedor sin red (CI).

---

## 5. Datos

### Lo que hay

| Fuente | Dónde | Para qué |
|---|---|---|
| Documentos sintéticos de los 16 tipos (digital, escaneado, foto) | `mrzlab/sintetico_docs.py` | Tests (D, E, N) y medición |
| 3 títulos reales (diploma FLC con capa de texto, FP y máster escaneados) | `datos/reales/` (fuera del repo) | Nivel R de H2 |
| Contrato indefinido del **SEPE** y registro de entrega de **EPI** (formularios oficiales en blanco) | `datos/publicos/` → `datos/formularios/` rellenados con datos ficticios | Nivel R de H5 con maquetas reales |
| Guías y documentos públicos de prevención (INSST, CARM, SS, BOE) | `datos/publicos/` | Negativos del clasificador; formato de títulos (RD 1002/2010, RD 22/2015) |

Documentos públicos usados: [modelos de contrato del SEPE](https://www.sepe.es/HomeSepe/es/empresas/Contratos-de-trabajo/modelos-contrato.html),
[registro de entrega de EPI (IRNAS-CSIC)](https://www.irnas.csic.es/wp-content/uploads/2024/06/PRL_ENTREGA-INF_-02-entrega-EPI-01-06-2024.pdf),
[RD 1002/2010 (títulos universitarios)](https://www.boe.es/buscar/pdf/2010/BOE-A-2010-12621-consolidado.pdf).
Certificados TGSS, AEAT, REA y de seguro RC de empresas y entidades se encuentran publicados por
sus titulares (portales de transparencia, licitaciones): 14 en `datos/internet/` con su
`verdad.csv`. No se han encontrado diplomas FLC ni documentos del trabajador: son documentos personales. Se generan desde sus sedes (TGSS y AEAT en el momento) o se piden con
consentimiento.

### Lo que hay que conseguir

- **30–50 documentos reales por tipo**, con consentimiento ([CONSENTIMIENTO.md](../CONSENTIMIENTO.md)),
  mezclando PDF digital, escaneado y foto. De cada documento, el PDF original **y** una foto de
  móvil: dos casos con la misma verdad.
- Fuera del repo: `datos/<lote>/` con los documentos y `verdad.csv` (`archivo,tipo,campo,valor`).
- **Nunca** subir documentos reales, CSV con datos reales ni plantillas aprendidas de ellos.

### Datasets públicos (revisar la licencia antes de usarlos)

| Dataset | Aporta | Uso previsto |
|---|---|---|
| [MIDV-2020](https://l3i-share.univ-lr.fr/MIDV2020/midv2020.html) | DNI español ficticio en escaneo, foto y vídeo | DNI |
| [SIDTD](https://arxiv.org/pdf/2401.01858) | Falsificaciones de esos documentos | DNI (anti-fraude) |
| [XFUND](https://www.microsoft.com/en-us/research/?p=844183) | Formularios escaneados en español con pares clave-valor | Formularios (H3) |
| RVL-CDIP | Documentos escaneados en 16 clases | Negativos del clasificador |
