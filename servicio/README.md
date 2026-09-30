# Servicio OCR

API HTTP de producción, sin estado, sobre el núcleo de `mrzlab/`: el DNI y 16 tipos de documento
más (titulaciones, documentos de empresa y del trabajador). **Solo en localhost**: escucha en
`127.0.0.1` (o en la red interna de Docker) y no se expone. Diseño en
[OCR local multi-documento](../docs/ocr-multidocumento.md) y plan en [Roadmap](../docs/roadmap.md).

```bash
docker compose --profile servicio up --build servicio     # http://127.0.0.1:8001
```

Variables: `OCR_API_KEY` (obligatoria; sin ella no arranca) u `OCR_ALLOW_ANONYMOUS=true` solo en
local. `GET /health` no pide clave.

## DNI: `POST /v1/dni/verificar`

Verifica un DNI español a partir de las fotos del **anverso** y del **reverso** y del nº de DNI
que indica el usuario, con OCR local (Tesseract + RapidOCR, sin nube).

**No se almacena ninguna imagen.** Las fotos se procesan en memoria, no se escriben en disco (ni
como fichero temporal de la subida) ni se registran en logs, y se descartan al responder. En los
logs solo quedan el estado, el motivo y el tiempo.

### Regla

**VERIFICADO** (100 %) si:
1. el nº de DNI coincide en el anverso, en el reverso (MRZ con todos los dígitos de control) y con
   el que declara el usuario, y
2. el nº de soporte coincide en el anverso y en el reverso.

Si no:

| Estado | Motivo | Cuándo |
|---|---|---|
| `REPETIR` | `MALA_CALIDAD` | No se lee alguna cara y esa foto tiene mala calidad. Solo en el intento 1 |
| `REVISION_ADMIN` | `INTENTOS_AGOTADOS` | Intento 2 y vuelve a fallar por calidad |
| `REVISION_ADMIN` | `LECTURA_FALLIDA` | No se lee y la calidad es buena: repetir no ayudaría |
| `REVISION_ADMIN` | `DATOS_NO_COINCIDEN` | Se lee, pero algún DNI o el soporte no coinciden |

El servicio **no guarda estado**: quien llama guarda el nº de intento (1 o 2), y en
`REVISION_ADMIN` avisa a una persona con `datos_*`, `comprobaciones`, `calidad` y `detalle`.

### Petición y respuesta

`POST /v1/dni/verificar` (multipart; con la cabecera `X-Api-Key` del servicio)

| Campo | Tipo | |
|---|---|---|
| `anverso` | archivo | JPG, PNG o WEBP, máx. 15 MB |
| `reverso` | archivo | Ídem, con la MRZ visible |
| `dni_declarado` | texto | Se normaliza: `12.345.678-z` → `12345678Z` |
| `intento` | entero | `1` (por defecto) o `2` |

Respuesta (200):

```json
{
  "estado": "VERIFICADO",
  "motivo": "OK",
  "intento": 1,
  "intentos_max": 2,
  "comprobaciones": {
    "mrz_valida": true,
    "dni_anverso_leido": true,
    "soporte_anverso_leido": true,
    "dni_anverso_igual_reverso": true,
    "dni_reverso_igual_declarado": true,
    "dni_anverso_igual_declarado": true,
    "soporte_anverso_igual_reverso": true
  },
  "datos_reverso": {
    "dni": "12345678Z", "num_soporte": "BAA000589", "nombre": "LUIS", "apellidos": "GOMEZ RUIZ",
    "nacionalidad": "ESP", "fecha_nacimiento": "17/04/1990", "fecha_caducidad": "02/10/2034"
  },
  "datos_anverso": {"dni": "12345678Z", "num_soporte": "BAA000589"},
  "calidad": {
    "anverso": {"veredicto": "apta", "avisos": []},
    "reverso": {"veredicto": "apta", "avisos": []}
  },
  "instrucciones": [],
  "avisos": [],
  "detalle": ""
}
```

- `comprobaciones`: `null` cuando no se puede comparar (falta uno de los dos datos).
- `instrucciones`: solo en `REPETIR`; qué corregir en cada cara («Reverso: La foto está borrosa…»).
- `avisos`: informativos, no cambian el estado (p. ej. «El DNI está caducado.»).
- Errores: `400` si una foto no es una imagen o `intento` no es 1 o 2; `413` si pasa de 15 MB.

## Qué protege cada dato

- Nº de DNI, fechas y dígitos del soporte: dígitos de control de la MRZ.
- Letras del soporte: solo en parte (M/W, F/P… dan el mismo control). Por eso se compara con el
  anverso.
- Nombre y apellidos: sin control. Se devuelven para contrastarlos con los declarados.

### Plantilla de posiciones del anverso

Si existe `plantillas/anverso.yaml` (se genera con «Aprender posiciones» en el lab; solo
coordenadas, sin datos personales), el DNI y el soporte del anverso se leen también por su
posición en la tarjeta. Sin plantilla se leen junto a su etiqueta.

## Modelo `mrz` de Tesseract (AGPL)

La imagen lo incluye por defecto (para evaluar en el lab). Para producción, mientras no se
resuelva su licencia (ver «Licencias» en el [README](../README.md)), constrúyela sin él:
`docker build --build-arg INCLUIR_MODELO_MRZ_AGPL=false .` Sin él, la MRZ la lee RapidOCR.

## Documentos: `/v1/documentos`

Títulos, certificados, pólizas, contratos y fichas. Mismas reglas que el DNI: solo en localhost,
sin estado, en memoria y sin datos en los logs. Contrato completo en
[docs/openapi.json](../docs/openapi.json) y un ejemplo de respuesta por tipo en
[docs/ejemplos/](../docs/ejemplos/).

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/v1/documentos/tipos` | Tipos, sus campos y cuáles son obligatorios |
| `POST` | `/v1/documentos/{tipo}/extraer` | Lee un documento (`archivo`: PDF, JPG, PNG o WEBP; máx. 15 MB) |
| `POST` | `/v1/documentos/clasificar` | Qué tipo de documento parece |

Tipos: `flc_60h`, `ts_riesgos`, `ts_prl` (titulaciones); `certificado_tgss`, `certificado_aeat`,
`seguro_rc`, `registro_empresa`, `apertura_centro_trabajo`, `plan_seguridad_salud`,
`evaluacion_riesgos`, `cae_documentacion` (empresa); `contrato_laboral`, `reconocimiento_medico`,
`informacion_art18`, `formacion_art19`, `entrega_epis` (trabajador).

### Cómo se lee

- **PDF con capa de texto**: se lee el texto (y los campos de formulario sin aplanar) sin OCR.
- **PDF escaneado o foto**: la hoja se busca y endereza, se orienta y se corrige la inclinación;
  después Tesseract lee la página. En fotos, o si Tesseract duda, RapidOCR encuentra las líneas y
  cada una la reconocen los dos motores.
- **Autenticidad**: firma PAdES (íntegra, cubre todo el documento, modificada después), CSV/CEA
  (solo si se confirma con los dos motores: no tiene dígito de control) y QR.

### Respuesta

```json
{
  "tipo": "certificado_tgss",
  "lectura": "COMPLETA",
  "origen": "pdf_digital",
  "paginas": 1,
  "campos": {
    "identificador": {"valor": "B12345674", "origen": "capa_texto", "confianza": 1.0, "pagina": 1},
    "fecha_emision": {"valor": "2025-01-10", "origen": "capa_texto", "confianza": 1.0, "pagina": 1},
    "al_corriente": {"valor": true, "origen": "capa_texto", "confianza": 1.0, "pagina": 1},
    "caduca": {"valor": "2025-07-10", "origen": "calculado", "confianza": 1.0, "pagina": 1}
  },
  "validaciones": {"identificador_valido": true, "vigente": false, "al_corriente": true},
  "clasificacion": {"tipo_detectado": "certificado_tgss", "confianza": 0.71, "candidatos": [], "coincide": true},
  "autenticidad": {"firmas": [], "codigos_verificacion": [{"tipo": "CSV", "codigo": "ABCD1234EFGH5678"}],
                   "qr": [], "avisos": []},
  "calidad": {"veredicto": "apta", "avisos": []},
  "avisos": [],
  "tiempo_ms": 64
}
```

| `lectura` | Qué hacer |
|---|---|
| `COMPLETA` | Están todos los campos obligatorios: comparar con los datos propios y decidir |
| `INCOMPLETA` | Faltan campos y la calidad es buena: revisión manual |
| `ILEGIBLE` | Faltan campos y la calidad es mala: pedir otra foto o escaneo (`calidad.avisos` dice qué corregir) |
| `OTRO_DOCUMENTO` | Se ha subido otro tipo de documento (`clasificacion.tipo_detectado`) |

**Un campo que no pasa su propia validación no se devuelve** (un NIF con la letra mal, un CIF de
otra casilla, una fecha ilegible): mejor vacío que erróneo. `validaciones` dice lo que el propio
documento permite comprobar (letra del NIF, horas, vigencia, título oficial, firmado…); comparar
con el perfil de la persona o la empresa es cosa de quien llama.

Errores: `400` vacío, corrupto o cifrado · `404` tipo desconocido · `413` más de 15 MB · `415`
formato no admitido · `422` demasiadas páginas (5; 25 en contratos, 60 en documentos libres) ·
`503` hace falta OCR y no hay motores.

Datos de salud: en `reconocimiento_medico` solo se devuelven NIF, fecha y resultado (apto / no
apto / con restricciones), nunca el resto del texto.

## Código

El servicio usa directamente los módulos de `mrzlab/` (los mismos que el lab): lo que se
calibra en el lab es lo que corre en producción. Lo propio del servicio: `lectura.py`,
`verificacion.py`, `documentos.py`, `api.py` y `app.py`. Tests en `tests/test_servicio.py` y
`tests/test_documentos_api.py`.
