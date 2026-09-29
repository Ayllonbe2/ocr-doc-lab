# Roadmap: OCR local para todos los documentos

Plan de desarrollo para llevar el OCR del DNI a **todos los tipos de documento** (titulaciones,
certificados, pólizas, contratos, fichas firmadas…), con sus pruebas, y sustituir por completo un
OCR en la nube. Diseño general en [OCR local multi-documento](ocr-multidocumento.md).

Estado: propuesta.

## Reglas

- **Todo en localhost.** El servicio escucha solo en `127.0.0.1` (o en la red interna de Docker
  del mismo servidor). No se publica como API en internet, no tiene subdominio y ningún documento
  sale de la máquina.
- **Sin nube y sin telemetría.** Solo motores locales (Tesseract, RapidOCR, PaddleOCR); se
  comprueba que el contenedor no hace conexiones salientes.
- **Sin estado y sin guardar nada.** Los bytes llegan en la petición, se procesan en memoria (sin
  ficheros temporales) y se descartan. Los logs solo llevan tipo, resultado y tiempo.
- **El OCR lee; no decide.** Devuelve qué pone el documento y si es coherente consigo mismo
  (letra del NIF, fechas, horas, firma…). Comparar con los datos del usuario y aceptar o rechazar
  es cosa de quien llama.
- **Métrica que manda: 0 datos erróneos dados por buenos.** Mejor pedir otra foto o pasar a
  revisión manual que inventar un dato.
- **Licencias permisivas.** Nada AGPL/GPL en el servicio (por eso no PyMuPDF; el modelo `mrz` de
  Tesseract sigue desactivado por defecto).

---

## 1. Contrato común

### Endpoints (en `http://127.0.0.1:8001`)

| Método | Ruta | Qué hace | Estado |
|---|---|---|---|
| `GET` | `/health` | Estado del servicio; añadir motores disponibles y versión de extractores | Existe |
| `POST` | `/v1/dni/verificar` | Flujo completo del DNI | Existe |
| `GET` | `/v1/documentos/tipos` | Tipos admitidos, sus campos y validaciones | Nuevo |
| `POST` | `/v1/documentos/{tipo}/extraer` | Lee un documento del tipo indicado | Nuevo |
| `POST` | `/v1/documentos/clasificar` | Dice qué tipo de documento es | Nuevo |

### Petición (`multipart/form-data`)

| Campo | Tipo | |
|---|---|---|
| `archivo` | fichero | PDF, JPG, PNG, WEBP · máx. 15 MB · PDF máx. 5 páginas (configurable) |

La clave `X-Api-Key` se mantiene como segunda barrera por si otro proceso de la máquina llama al
puerto; no sustituye a que el puerto no esté expuesto.

### Respuesta (200)

```json
{
  "tipo": "flc_60h",
  "lectura": "COMPLETA",
  "origen": "pdf_digital",
  "paginas": 2,
  "campos": {
    "titular": {"valor": "GOMEZ RUIZ, LUIS", "origen": "capa_texto", "confianza": 1.0, "pagina": 1},
    "nif":     {"valor": "12345678Z", "origen": "capa_texto", "confianza": 1.0, "pagina": 1},
    "horas":   {"valor": 60, "origen": "capa_texto", "confianza": 1.0, "pagina": 1},
    "fecha":   {"valor": "2025-03-14", "origen": "capa_texto", "confianza": 1.0, "pagina": 1}
  },
  "validaciones": {"nif_letra_valida": true, "horas_60": true, "menciona_flc": true, "fecha_no_futura": true},
  "clasificacion": {"tipo_detectado": "flc_60h", "coincide": true, "confianza": 0.92},
  "autenticidad": {"firma": null, "csv": null, "qr": null, "avisos": []},
  "calidad": {"veredicto": "apta", "avisos": []},
  "avisos": [],
  "tiempo_ms": 180
}
```

- `lectura`: `COMPLETA` (todos los campos obligatorios) · `INCOMPLETA` (faltan campos con buena
  calidad → revisión manual) · `ILEGIBLE` (mala calidad → pedir otra foto o escaneo).
- `origen`: `pdf_digital` · `pdf_escaneado` · `pdf_mixto` · `imagen`. Cada campo lleva el suyo
  (`capa_texto` u `ocr:<motor>`).
- `autenticidad.firma`: `{valida, firmante, integra}` si el PDF tiene firma PAdES.
  `csv` / `qr`: el código leído, para comprobarlo en la sede del organismo emisor.

### Errores

| Código | Cuándo |
|---|---|
| 400 | Fichero vacío, corrupto o PDF cifrado |
| 401 | Falta o no vale `X-Api-Key` |
| 404 | `{tipo}` no existe |
| 413 | Más de 15 MB |
| 415 | Formato no admitido |
| 422 | PDF con más páginas del límite |
| 503 | Ningún motor OCR disponible (un PDF digital sigue funcionando sin OCR) |

### Tres caminos según la entrada

```
                  ┌─ PDF con capa de texto ──► texto + posiciones, sin OCR          ◄ exacto
archivo ─► entrada ┼─ PDF escaneado ─────────► render 300 ppp ─► OCR                ◄ medio
                  └─ foto de móvil ─────────► calidad ─► enderezar hoja ─► OCR      ◄ difícil
                                                          │
                     mismo extractor por tipo ◄───────────┘  (recibe líneas: texto + caja + origen)
```

Se decide **por página** (hay PDFs mixtos). Antes del OCR se buscan pruebas de autenticidad
(firma, CSV, QR, metadatos de edición), que valen más que cualquier lectura.

---

## 2. Estructura del código

```
mrzlab/
  entrada.py          # imagen / PDF digital / escaneado / mixto, por página
  pdf.py              # texto con posiciones (pdfplumber) y render (pypdfium2)
  autenticidad.py     # firma PAdES (pyHanko), CSV por regex, QR (cv2.QRCodeDetector), metadatos
  pagina.py           # hoja A4 en foto: detectar, perspectiva, orientación (Tesseract OSD), deskew
  lineas.py           # Linea(texto, caja, pagina, origen, confianza): lo que reciben los extractores
  validadores.py      # NIF / NIE / CIF, fechas españolas, importes
  clasificador.py     # tipo de documento por palabras clave con peso
  extractores/
    base.py           # Extractor: tipo, campos, obligatorios, extraer(lineas), validar(campos)
    flc_60h.py  ts_riesgos.py  ts_prl.py
    certificado_tgss.py  certificado_aeat.py  seguro_rc.py  registro_empresa.py
    apertura_centro.py  documento_libre.py
    contrato_laboral.py  reconocimiento_medico.py  ficha_firmada.py
  sintetico_docs.py   # plantillas con datos ficticios → PDF digital, escaneado y foto degradada
servicio/
  documentos.py       # router /v1/documentos/*
herramientas/
  medir.py            # lote real (fuera del repo) + verdad.csv → informe por campo y por origen
tests/
  extractores/test_<tipo>.py  test_entrada.py  test_pdf.py  test_autenticidad.py
  test_validadores.py  test_clasificador.py  test_pagina.py  test_documentos_api.py
```

Dependencias nuevas: `pypdfium2`, `pdfplumber`, `pyHanko`. Solo en desarrollo: `reportlab` (PDF
con capa de texto en los tests), `augraphy` (degradar a escaneo/foto), `pip-licenses`.

---

## 3. Pruebas

Cada extractor pasa por los mismos niveles:

| Nivel | Qué prueba | Datos | ¿En CI? |
|---|---|---|---|
| **U** unitario | `extraer(lineas)` y `validar(campos)` con líneas escritas a mano, sin OCR | En el test | Sí |
| **D** PDF digital | Plantilla → PDF con `reportlab` → endpoint → campos exactos | `sintetico_docs.py` | Sí |
| **E** escaneado / foto | Plantilla → imagen → degradación → OCR real | `sintetico_docs.py` + Augraphy | Sí, `@pytest.mark.ocr` (lento) |
| **N** negativos | Otro tipo, página en blanco, corrupto, cifrado, foto ilegible | Sintéticos | Sí |
| **A** API | Contrato, errores, límites, no escribe en disco, logs sin datos | Sintéticos | Sí |
| **R** regresión real | `herramientas/medir.py` con `verdad.csv` | Reales con consentimiento, **fuera del repo** | No: a mano antes de dar un tipo por bueno |

- **Contrato versionado:** se exporta `docs/openapi.json` y un ejemplo de respuesta por tipo en
  `docs/ejemplos/`; un test falla si el contrato cambia sin actualizarlos.
- **Red:** un test de extremo a extremo con la red del contenedor cortada (`network_mode: none`)
  procesa un documento de cada tipo.

**Criterio para dar un tipo por bueno (nivel R):**
- 0 campos erróneos con `lectura = COMPLETA`.
- `COMPLETA` en ≥ 95 % de PDF digitales, ≥ 80 % de escaneados, ≥ 60 % de fotos (el resto,
  `ILEGIBLE` o `INCOMPLETA`, nunca un dato inventado).
- p95 por página: < 1 s en PDF digital, < 6 s con OCR, con 2 CPU.

### Errores típicos que las pruebas deben impedir

| Error | Test |
|---|---|
| Convertir en imagen un PDF que ya tiene texto (más lento y con errores de lectura) | `test_pdf_digital_no_pasa_por_ocr` (el motor OCR falla si se le llama) |
| Leer solo la primera página | `test_campo_en_pagina_2_se_encuentra` |
| Rellenar un campo con un valor fijo en vez de leerlo, de modo que la validación nunca falla | `test_ts_riesgos_documento_cualquiera_no_da_titulo` |
| Aceptar un solo formato de nº de registro FLC cuando hay varios | `test_flc_numero_registro_formatos` (incluido `NNNNNN/NNNNNN/NNNNNNN`) |
| Tomar el primer "NN horas" del texto sin contexto | `test_flc_horas_solo_del_titulo_del_curso` |
| Coger el NIF del centro o de la aseguradora en vez del del titular | `test_<tipo>_varios_nif_elige_titular` |
| Dependencias AGPL/GPL | `pip-licenses` en CI |

---

## 4. Hitos

Tamaños: S ≈ días · M ≈ 1–2 semanas · L ≈ 3+ semanas (una persona).

### H1 — Núcleo de documentos (M)

- [ ] `entrada.py`, `pdf.py`, `lineas.py`, `validadores.py`, `autenticidad.py`, `extractores/base.py`.
- [ ] Router `servicio/documentos.py` con un tipo de prueba (`demo`), límites, errores y
      privacidad como en el DNI.
- [ ] `sintetico_docs.py` reutilizando las degradaciones de `sintetico.py`.
- [ ] `herramientas/medir.py`.
- [ ] CI: `pip-licenses` y test sin red.

Pruebas:
- [ ] `test_entrada.py`: PDF digital, "Imprimir a PDF" de una imagen (escaneado), mixto por
      página, imagen con EXIF girado, cifrado → 400, corrupto → 400, 6 páginas → 422.
- [ ] `test_pdf.py`: cajas en coordenadas de página; PDF digital sin OCR; campo en página 2.
- [ ] `test_autenticidad.py`: PDF firmado con un certificado de prueba → válido; modificado tras
      firmar → `integra: false`; CSV por regex; QR generado en la prueba.
- [ ] `test_validadores.py`: letra de NIF/NIE, dígito de control del CIF, fechas ("14 de marzo de
      2025", "14/03/2025", "14-03-25").
- [ ] `test_documentos_api.py`: 401, 404, 413, 415, 422; no escribe en disco; logs sin datos.

Hecho cuando: el tipo `demo` pasa D, E, N y A en CI.

### H2 — Titulaciones de prevención (M)

| Tipo | Campos obligatorios | Validaciones |
|---|---|---|
| `flc_60h` | titular, nif, horas, numero_registro, fecha | NIF válido; 60 h **en la frase del curso**; menciona FLC / Convenio de la Construcción; fecha ≤ hoy |
| `ts_riesgos` | titular, nif, titulo, fecha | título **leído** con TÉCNICO SUPERIOR + PREVENCIÓN + RIESGOS; NIF válido; CCAA y nº de registro si aparecen |
| `ts_prl` | titular, titulo, universidad, fecha | "Máster Universitario" + PRL en el título; `titulo_oficial` leído del texto; nº del Registro Nacional de Títulos si aparece |

- [ ] Extractores por etiqueta + posición; plantilla de posiciones para el diploma FLC.
- [ ] Plantillas sintéticas de los tres tipos.

Pruebas (U·D·E·N·A por tipo):
- [ ] Casos buenos; NIF con letra mala; varios NIF; fechas en letra.
- [ ] Máster **propio** → `titulo_oficial: false`; curso de 20 h como `flc_60h` → `horas_60: false`;
      diploma FLC enviado como `ts_prl` → `clasificacion.coincide: false`.
- [ ] Escaneado a 150 y 300 ppp; foto con sombra, perspectiva y desenfoque ligero.
- [ ] R: lote real (§5).

Hecho cuando: los tres tipos cumplen el criterio de §3 en PDF digital y escaneado.

### H3 — Clasificador y fotos de documentos A4 (L) · la parte difícil

- [ ] `clasificador.py` + `POST /v1/documentos/clasificar` (`{tipo_detectado, confianza, candidatos}`).
- [ ] `pagina.py`: detectar la hoja, perspectiva, orientación 0/90/180/270, deskew.
- [ ] Calidad para A4 con umbrales propios en `umbrales.yaml` (altura de letra en px, sombras,
      reflejos) → `ILEGIBLE` con instrucciones, como en el DNI.
- [ ] Fondos decorativos (orlas, sellos, marcas de agua): binarización adaptativa y quitar color.
- [ ] Comparar motores por tipo (Tesseract `spa`, RapidOCR, PaddleOCR latino) con `medir.py`.
- [ ] Lab: selector de tipo de documento y lote por tipo.

Pruebas:
- [ ] Matriz de confusión del clasificador con sintéticos de todos los tipos + negativos: ningún
      tipo confundido con otro con confianza alta.
- [ ] Foto sintética girada 90/180/270 y con perspectiva → texto recuperado.
- [ ] Foto oscura o borrosa → `ILEGIBLE` con aviso concreto.
- [ ] R: fotos de móvil de los documentos del lote; XFUND (español) para "etiqueta → valor".

Hecho cuando: las titulaciones cumplen el criterio de §3 también en foto.

### H4 — Documentos de empresa (M–L)

| Tipo | Campos | Validaciones |
|---|---|---|
| `certificado_tgss` | razon_social, cif, fecha_emision, al_corriente, csv | CIF válido; caduca a los 6 meses de la emisión; firma PAdES si la hay |
| `certificado_aeat` | ídem | ídem |
| `seguro_rc` | tomador, cif, aseguradora, poliza, vigencia_desde, vigencia_hasta, limite_siniestro | vigencia en curso; importe leído |
| `registro_empresa` | cif, numero_inscripcion, fecha | CIF válido |
| `apertura_centro_trabajo` | cif, direccion_obra, fecha | CIF válido |
| `plan_seguridad_salud`, `evaluacion_riesgos`, `cae_documentacion` | cif o razón social, fecha | solo clasificación y fecha: texto libre y largo, sin extracción de campos |

Orden: TGSS → AEAT → RC → registro y apertura → documentos libres.

Pruebas (U·D·E·N·A por tipo), además:
- [ ] Certificado firmado de prueba → `firma.valida`; alterado → `integra: false`.
- [ ] Emitido hace 7 meses → aviso de caducado.
- [ ] Póliza con el CIF de la aseguradora y el del tomador → se elige el del tomador.

### H5 — Documentos de prevención del trabajador (M)

| Tipo | Campos | Nota |
|---|---|---|
| `contrato_laboral` | nif_trabajador, cif_empresa, fecha_inicio, tipo_contrato | |
| `reconocimiento_medico` | nif, fecha, apto (sí / no / con restricciones) | **Datos de salud (art. 9 RGPD): solo estos campos**, nunca diagnóstico ni texto |
| `informacion_art18`, `formacion_art19`, `entrega_epis` | nif_trabajador, fecha, firmado | detector de firma manuscrita en la zona de firma |

Pruebas (U·D·E·N·A por tipo), además:
- [ ] `reconocimiento_medico`: el JSON **no contiene** ningún texto del documento fuera de los
      campos permitidos (se buscan frases del sintético en la respuesta).
- [ ] Ficha sin firmar → `firmado: false`; con firma sintética → `true`.

### H6 — Sustituir el OCR en la nube (M)

1. [ ] **En paralelo:** quien llama usa los dos OCR durante 2–4 semanas y compara solo campos y
       resultado (nunca imagen ni texto).
2. [ ] **Cambio por tipo** cuando el local cumple §3 y no es peor que la nube en datos erróneos
       dados por buenos.
3. [ ] **Retirar** el cliente de la nube, sus credenciales y variables, y su mención en la
       política de privacidad.

Pruebas:
- [ ] Un documento de cada tipo de extremo a extremo con el contenedor sin red.

---

## 5. Datos

### Lo que hay

| Fuente | Útil para |
|---|---|
| `mrzlab/sintetico.py` — degradaciones (desenfoque, luz, reflejo, perspectiva, sombra, ruido, movimiento) | Base de `sintetico_docs.py` |
| `tests/` — 84 tests del DNI | Patrón de los tests nuevos |
| Muestras reales fuera del repo: un diploma FLC de 60 h con capa de texto y dos títulos escaneados sin capa de texto (FP superior y máster) | Primeros casos de R en H2 (digital y escaneado) |
| Varios PDF genéricos de prevención (guías, formularios, un documento de otro país) | Solo negativos del clasificador |

No hay ninguna muestra real de documentos de empresa ni de prevención del trabajador.

### Lo que hay que conseguir

- **30–50 documentos reales por tipo**, con consentimiento ([CONSENTIMIENTO.md](../CONSENTIMIENTO.md)),
  mezclando PDF digital, escaneado y foto. De cada documento, el PDF original **y** una foto de
  móvil: dos casos con una sola fila de `verdad.csv`.
- Fuera del repo: `datos/<tipo>/{digital,escaneado,foto}/` + `datos/<tipo>/verdad.csv`.
- **Nunca** subir documentos reales, CSV con datos reales ni plantillas aprendidas de ellos.

### Datasets públicos (revisar la licencia de cada uno antes de usarlo)

| Dataset | Aporta | Hito |
|---|---|---|
| [MIDV-2020](https://l3i-share.univ-lr.fr/MIDV2020/midv2020.html) | DNI español ficticio (entre 10 países) en escaneo, foto y vídeo, con campos anotados | DNI |
| [SIDTD](https://arxiv.org/pdf/2401.01858) | Falsificaciones de esos documentos (recorte y sustitución, inpainting) | DNI (anti-fraude) |
| [XFUND](https://www.microsoft.com/en-us/research/?p=844183) | Formularios escaneados **en español** con pares clave-valor anotados | H3 |
| RVL-CDIP | Documentos escaneados en 16 clases | H3 (negativos del clasificador) |

Ninguno contiene diplomas FLC, títulos de PRL ni certificados de la TGSS o la AEAT: para esos,
plantillas sintéticas (CI) + lote real (medición).

---

## 6. Orden

```
H1 Núcleo ──► H2 Titulaciones (digital, escaneado) ──► H6 cambio de titulaciones
         ├──► H3 Clasificador + fotos A4 ──► H2 en foto
         ├──► H4 Empresa (TGSS y AEAT primero)
         └──► H5 Prevención del trabajador
```

H2 en PDF digital es lo primero que da valor; H3 es lo más costoso.
