# LEY.DO

**LEY.DO** es un archivo público independiente de referencia para documentos legales dominicanos.

LEY.DO no es una página oficial del Gobierno dominicano.  
LEY.DO no ofrece asesoría legal.  
LEY.DO no crea, interpreta ni certifica la ley.

El proyecto recopila, organiza, transcribe, versiona y publica documentos legales públicos provenientes de fuentes oficiales dominicanas.

## Regla de idioma

El idioma público del proyecto es **español**.

Los documentos, páginas, plantillas, estados, instrucciones editoriales, metadata pública y contenido publicado deben estar en español.

Solo se mantienen en inglés los nombres técnicos inevitables, como comandos, paquetes, archivos de configuración o convenciones propias de herramientas externas.

## Misión

Construir un corpus público, versionado en Git, auditable y legible por inteligencia artificial de documentos legales dominicanos, incluyendo:

- textos constitucionales
- leyes
- decretos
- resoluciones
- proyectos de ley
- documentos legales públicos relacionados

## Principios

### Independencia

LEY.DO no representa al Estado dominicano ni a ninguna institución pública.

### Trazabilidad

Cada documento debe preservar enlaces hacia su fuente oficial.

### Auditoría

Cada cambio debe poder revisarse mediante Git.

### Revisión humana

La automatización puede preparar documentos, pero la publicación requiere aprobación humana.

### No invención

El sistema nunca debe inventar texto legal faltante. Si una extracción es incierta, debe marcarse como pendiente de revisión.

## Estructura inicial del repositorio

```text
docs/
  index.md
  constitucion/
  leyes/
  decretos/
  resoluciones/
  proyectos/
  api/
  certificados/
  acerca/
fuentes/
  fuentes_oficiales.json
datos/
  corpus.json
  leyes.json
  decretos.json
scripts/
  ingesta/
  normalizar/
  publicar/
mkdocs.yml
README.md
LICENSE
DESCARGO.md
```

## Metadata mínima por documento

Cada documento debe tener:

| Campo | Descripción |
|---|---|
| `tipo_documento` | Constitución, ley, decreto, resolución, proyecto u otro |
| `numero` | Número oficial del documento, si aplica |
| `anio` | Año del documento |
| `titulo` | Título oficial o título normalizado |
| `fecha` | Fecha oficial del documento |
| `url_fuente_oficial` | Página oficial donde se encontró el documento |
| `url_pdf_original` | Enlace directo al PDF original, si existe |
| `ruta_pdf_local` | Ruta local del PDF dentro del repositorio |
| `ruta_markdown` | Ruta local de la transcripción en Markdown |
| `ruta_json` | Ruta local del archivo JSON |
| `sha256_pdf_original` | Hash SHA256 del PDF original |
| `sha256_markdown` | Hash SHA256 del archivo Markdown |
| `estado_revision` | Estado de revisión humana |
| `estado_publicacion` | Estado de publicación |
| `commit_publicacion` | ID del commit donde fue publicado |
| `notas` | Notas humanas o del agente |

## Estados permitidos

Los estados permitidos son:

- `descubierto`
- `descargado`
- `extraido`
- `normalizado`
- `pendiente_revision`
- `aprobado`
- `publicado`
- `rechazado`
- `archivado`
- `error`

## Reglas del agente

El agente puede:

- descubrir documentos en fuentes oficiales
- descargar documentos
- extraer texto
- normalizar metadata
- preparar archivos Markdown y JSON
- calcular hashes SHA256
- abrir pull requests o crear elementos de revisión

El agente no puede:

- publicar directamente sin aprobación humana
- inventar texto legal faltante
- eliminar enlaces a fuentes oficiales
- certificar validez legal
- ofrecer asesoría legal

Toda extracción incierta debe marcarse como `pendiente_revision`.

## Primer MVP

1. Crear página inicial.
2. Crear página de descargo.
3. Crear repositorio público en GitHub.
4. Crear sitio con MkDocs Material.
5. Publicar en Cloudflare Pages.
6. Agregar la Constitución.
7. Agregar 10 leyes recientes.
8. Agregar 10 decretos recientes.
9. Publicar PDF, Markdown, JSON y hash por cada documento.
10. Agregar búsqueda.
11. Agregar página de donación más adelante.

## Desarrollo local

Instalar dependencias:

```bash
pip install mkdocs mkdocs-material
```

Ejecutar sitio local:

```bash
mkdocs serve
```

Construir sitio estático:

```bash
mkdocs build
```

El sitio generado aparecerá en:

```text
site/
```

## Descargo

Ver [`DESCARGO.md`](DESCARGO.md).
