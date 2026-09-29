# Servicio OCR

API HTTP de producción, sin estado, sobre el núcleo de `mrzlab/`. Hoy tiene un documento: el DNI.
La idea es añadir más tipos de documento (ver [OCR local multi-documento](../docs/ocr-multidocumento.md)).

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

## Código

El servicio usa directamente los módulos de `mrzlab/` (los mismos que el lab): lo que se
calibra en el lab es lo que corre en producción. Lo propio del servicio: `lectura.py`,
`verificacion.py`, `api.py` y `app.py`. Tests en `tests/test_servicio.py`.
