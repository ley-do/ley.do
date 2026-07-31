#!/usr/bin/env python3
"""Normaliza PDFs oficiales de leyes de Consultoría Jurídica para LEY.DO."""
import argparse
import hashlib
import html
import json
import re
from datetime import date
from pathlib import Path

import pymupdf

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md_text(value, multiline=False):
    text = str(value or "").replace("\r", "")
    if not multiline:
        text = " ".join(text.splitlines()).strip()
    text = html.escape(text, quote=True)
    for char, entity in (("`", "&#96;"), ("[", "&#91;"), ("]", "&#93;"), ("|", "&#124;")):
        text = text.replace(char, entity)
    if multiline:
        text = re.sub(r"(?m)^([#>*+-])", r"\\\1", text)
    return text


def official_link(url):
    try:
        from scripts.procesar_decretos_consultoria import _markdown_url
    except ModuleNotFoundError:
        from procesar_decretos_consultoria import _markdown_url
    url = str(url or "").strip()
    if not url:
        return "no disponible"
    return f"[{md_text(url)}]({_markdown_url(url)})"


def nint(value):
    match = re.match(r"\s*0*(\d+)\s*-", str(value or ""))
    return int(match.group(1)) if match else None


def fecha_dado(pages):
    text = "\n".join(pages)
    markers = list(re.finditer(r"\bDAD[OA]\b", text, re.I))
    if not markers:
        return "", "clausula_dado_no_detectada"
    snippet = text[markers[-1].start(): markers[-1].start() + 900]
    month = re.search(r"\b(" + "|".join(MESES) + r")\b", snippet, re.I)
    if not month:
        return "", "clausula_dado_no_parseable"
    days = [int(x) for x in re.findall(r"\(\s*(\d{1,2})(?:\s*\)|(?:er\.)?\s*\))", snippet[: month.start()], re.I)]
    years = [int(x) for x in re.findall(r"(?:\(\s*)?(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)(?:\s*\))?", snippet[month.end():])]
    if not days or not years:
        return "", "clausula_dado_no_parseable"
    day = days[-1]
    month_number = MESES[month.group(1).lower()]
    observed_year = years[0]
    try:
        date(observed_year, month_number, day)
    except ValueError:
        return "", "clausula_dado_no_parseable"
    return f"{day:02d}/{month_number:02d}/{observed_year}", "detectada"


def reflow(text):
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.replace("\r", "").split("\n")]
    marker = re.compile(
        r"^(?:Ley\s+núm\.|EL CONGRESO NACIONAL|En Nombre de la República|CONSIDERANDO|VISTA|VISTO|ART[IÍ]CULO|PÁRRAFO|DADO)",
        re.I,
    )
    blocks = []
    current = []
    for line in lines:
        if re.fullmatch(r"-\s*\d+\s*-", line):
            continue
        if not line:
            if current:
                blocks.append(" ".join(current))
                current = []
        elif marker.match(line) and current:
            blocks.append(" ".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(" ".join(current))
    return "\n\n".join(blocks).strip()


def extract(pdf, number, yy):
    doc = pymupdf.open(pdf)
    texts = [page.get_text("text") for page in doc]
    doc.close()
    full_year = f"20{yy}" if len(yy) == 2 else yy
    year_token = rf"(?:{re.escape(yy)}|{re.escape(full_year)})"
    start = re.compile(
        rf"(?im)^Ley\s+núm\.\s*(?P<numero>0*{number}\s*-\s*{year_token})\b"
    )
    neighbor = re.compile(
        rf"(?im)^Ley\s+núm\.\s*(?P<numero>\d+)\s*-\s*(?P<anio>\d{{2}}|\d{{4}})\b"
    )
    begin = None
    for page_index, text in enumerate(texts):
        match = start.search(text)
        if match:
            begin = (page_index, match.start())
            break
    if begin is None:
        # some official PDFs put the law number only after EL CONGRESO
        alt = re.compile(rf"(?im)^EL CONGRESO NACIONAL\b")
        for page_index, text in enumerate(texts):
            if alt.search(text) and re.search(rf"(?i)Ley\s+núm\.\s*0*{number}\s*-\s*{year_token}\b", text):
                begin = (page_index, 0)
                break
    if begin is None:
        return [], "encabezado_no_encontrado", []
    pages = []
    trimmed = []
    for page_index, text in enumerate(texts):
        if page_index < begin[0]:
            continue
        chunk = text if page_index > begin[0] else text[begin[1]:]
        end = None
        for match in neighbor.finditer(chunk):
            candidate_number = int(match.group("numero"))
            candidate_year = match.group("anio")
            candidate_year_norm = candidate_year if len(candidate_year) == 4 else f"20{candidate_year}"
            target_year_norm = full_year if len(full_year) == 4 else f"20{full_year}"
            # Skip the opening header of the target law.
            if candidate_number == number and candidate_year_norm[-2:] == target_year_norm[-2:]:
                continue
            # Later law header in same recut.
            if match.start() > 40:
                end = match.start()
                trimmed.append(candidate_number)
                break
        if end is not None:
            chunk = chunk[:end]
        cleaned = reflow(chunk)
        if cleaned:
            pages.append(cleaned)
        if end is not None:
            break
    if not pages:
        return [], "segmentacion_vacia", trimmed
    return pages, "extraido_desde_pdf_oficial", trimmed


def title_from_pages(pages, number, year):
    if not pages:
        return f"Ley núm. {number:03d}-{year}"
    first = pages[0]
    match = re.search(rf"(?i)Ley\s+núm\.\s*0*{number}\s*-\s*\d{{2,4}}\s+(.+?)(?:\.\s*G\.|\n|$)", first)
    if match:
        return " ".join(match.group(1).split())[:240]
    return f"Ley núm. {number:03d}-{year}"


def write_package(repo, year, record, pages, state, trimmed):
    number = nint(record.get("numero"))
    if number is None:
        raise ValueError(f"Número inválido: {record.get('numero')}")
    stem = f"ley-{number:03d}-{year}"
    pdf = repo / f"archivos/leyes/{year}/{stem}.pdf"
    md_path = repo / f"docs/leyes/{year}/{stem}.md"
    json_path = repo / f"datos/leyes/{year}/{stem}.json"
    if not pdf.exists() or pdf.read_bytes()[:4] != b"%PDF":
        raise ValueError(f"PDF ausente o inválido: {pdf}")
    hpdf = sha(pdf)
    fecha_pdf, estado_fecha = fecha_dado(pages)
    fecha_fuente = str(record.get("fecha_documento") or "").strip()
    alertas = []
    if estado_fecha != "detectada":
        alertas.append("No se detectó una cláusula DADO parseable en el segmento extraído del PDF." if estado_fecha == "clausula_dado_no_detectada" else "La cláusula DADO del PDF no pudo parsearse sin inferencia.")
    elif fecha_fuente and fecha_pdf and fecha_fuente != fecha_pdf:
        alertas.append(
            f"La metadata oficial consultada indica {fecha_fuente}, mientras el apartado DADO del PDF indica {fecha_pdf}. Se conservan ambos valores para revisión humana."
        )
    title = title_from_pages(pages, number, year)
    text_body = "\n\n".join(f"### Página {index} del PDF\n\n{page}" for index, page in enumerate(pages, 1))
    md = "\n".join([
        f"# Ley núm. {number:03d}-{year}",
        "",
        '!!! warning "Aviso"',
        "    LEY.DO no es una fuente oficial. Verifique este documento contra la fuente oficial indicada.",
        "    LEY.DO no ofrece asesoría legal.",
        "",
        "## Metadata",
        "",
        f"- Tipo de documento: ley",
        f"- Número: {number}",
        f"- Año: {year}",
        f"- Fecha: {md_text(fecha_fuente or fecha_pdf or '')}",
        f"- Institución fuente: {md_text(record.get('institucion_fuente') or 'Consultoría Jurídica del Poder Ejecutivo')}",
        f"- Fuente oficial: {official_link(record.get('url_documento_consultoria_abrir') or record.get('url_fuente_oficial'))}",
        f"- PDF original: {official_link(record.get('url_documento_consultoria_descargar'))}",
        f"- Hash SHA256 del PDF: `{hpdf}`",
        f"- Estado de revisión: pendiente_revision",
        "",
        "## Texto",
        "",
        text_body if text_body.strip() else "_Texto pendiente de extracción legible._",
        "",
        "## Notas de revisión",
        "",
        "- Pendiente de revisión humana.",
        "- Texto extraído automáticamente desde PDF oficial; verificar contra el PDF.",
    ])
    if trimmed:
        md += "\n- El PDF contenía fragmentos de leyes o documentos vecinos; se delimitaron usando encabezados oficiales."
    for alert in alertas:
        md += f"\n- {md_text(alert)}"
    md += "\n"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8", newline="\n")
    hmd = sha(md_path)
    meta = {
        "tipo_documento": "ley",
        "numero": f"{number:03d}",
        "anio": str(year),
        "titulo": title,
        "fecha": fecha_fuente or fecha_pdf or "",
        "gaceta_oficial": record.get("gaceta_oficial", ""),
        "institucion_fuente": record.get("institucion_fuente") or "Consultoría Jurídica del Poder Ejecutivo",
        "url_fuente_oficial": record.get("url_fuente_oficial") or "https://www.consultoria.gov.do/consulta/",
        "url_pdf_original": record.get("url_documento_consultoria_descargar", ""),
        "url_documento_oficial": record.get("url_documento_consultoria_abrir", ""),
        "document_id_consultoria": record.get("document_id_consultoria", ""),
        "fecha_consulta": record.get("fecha_consulta") or date.today().isoformat(),
        "ruta_pdf_local": f"archivos/leyes/{year}/{stem}.pdf",
        "ruta_markdown": f"docs/leyes/{year}/{stem}.md",
        "ruta_json": f"datos/leyes/{year}/{stem}.json",
        "sha256_pdf_original": hpdf,
        "sha256_markdown": hmd,
        "estado_revision": "pendiente_revision",
        "estado_publicacion": "normalizado" if state == "extraido_desde_pdf_oficial" else "descubierto",
        "estado_extraccion": state,
        "fragmentos_documentos_vecinos_excluidos": trimmed,
        "fecha_texto_pdf_detectada": fecha_pdf,
        "estado_fecha_texto_pdf": estado_fecha,
        "commit_publicacion": "",
        "notas": "Texto extraído automáticamente desde PDF oficial; verificar contra el PDF antes de aprobar.",
    }
    if fecha_fuente and fecha_pdf and fecha_fuente != fecha_pdf:
        meta["fecha_metadata_fuente"] = fecha_fuente
    if alertas:
        meta["alertas_revision"] = alertas
    json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    # refresh markdown hash after final notes already included
    return stem, state, len(pages), hpdf, hmd


def run(repo, year, numbers=None):
    repo = Path(repo)
    inventory_path = repo / f"fuentes/consultoria_inventario_{year}_leyes_decretos.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = {}
    for record in inventory.get("documentos", {}).get("leyes", []):
        number = nint(record.get("numero"))
        if number is None:
            continue
        if numbers is not None and number not in numbers:
            continue
        records[number] = record
    if numbers is not None:
        missing = sorted(set(numbers) - set(records))
        if missing:
            raise ValueError(f"Números ausentes del inventario: {missing}")
    ordered = sorted(records)
    results = []
    for number in ordered:
        record = records[number]
        stem = f"ley-{number:03d}-{year}"
        pdf = repo / f"archivos/leyes/{year}/{stem}.pdf"
        pages, state, trimmed = extract(pdf, number, str(year)[-2:])
        stem, state, page_count, hpdf, hmd = write_package(repo, year, record, pages, state, trimmed)
        print(f"OK {stem}: {page_count} página(s), estado={state}, PDF {hpdf[:12]}…, MD {hmd[:12]}…")
        results.append({"numero": number, "stem": stem, "estado": state, "pages": page_count})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--anio", type=int, required=True)
    parser.add_argument("--numeros", default="", help="Lista separada por comas; vacío = todas las del inventario")
    args = parser.parse_args(argv)
    numbers = None
    if args.numeros.strip():
        numbers = sorted({int(item.strip()) for item in args.numeros.split(",") if item.strip()})
    run(args.repo, args.anio, numbers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
