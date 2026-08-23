#!/usr/bin/env python3
"""Regenera portadas anuales de decretos solo desde paquetes previamente validados."""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.procesar_decretos_consultoria import _atomic_write_text  # noqa: E402

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def normalize_date(value: str) -> str:
    value = " ".join(str(value or "").split())
    if not value:
        return ""
    if "|" in value:
        value = value.split("|", 1)[0].strip()
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", value)
    if match:
        return value
    match = re.fullmatch(r"(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+(\d{4})", value, re.I)
    if match:
        month = MESES.get(match.group(2).lower())
        if month:
            return f"{int(match.group(1)):02d}/{month:02d}/{int(match.group(3)):04d}"
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", value)
    if match:
        return f"{int(match.group(1)):02d}/{int(match.group(2)):02d}/{int(match.group(3)):04d}"
    return value


def short_title(title: str, limit: int = 160) -> str:
    text = " ".join(str(title or "").split())
    text = re.sub(r"^(decreto\s+n[uú]m\.?\s*\d+[\w.-]*\s*[,:-]?\s*)", "", text, flags=re.I).strip()
    letters = re.sub(r"[^A-Za-zÁÉÍÓÚÜáéíóúñÑ]", "", text)
    if letters and sum(char.isupper() for char in letters) / len(letters) > 0.8 and len(letters) > 12:
        text = text.lower()
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"


def is_generic(title: str, number: int, year: int) -> bool:
    text = " ".join(str(title or "").split())
    if not text:
        return True
    return bool(re.fullmatch(rf"Decreto\s*n[uú]m\.?\s*0*{number}(?:-{year}|-{str(year)[-2:]})?", text, flags=re.I))


def esc(value: str) -> str:
    return html.escape(str(value), quote=True)


def extract_notes(existing: str) -> list[str]:
    keep = {
        "salvedades documentales",
        "registros con numeración atípica",
        "notas de revisión",
        "notas editoriales",
    }
    notes = []
    for section in re.split(r"(?=^## )", existing, flags=re.M):
        first = section.splitlines()[0].strip().lower() if section.strip() else ""
        title = first[3:].strip() if first.startswith("## ") else ""
        if title in keep:
            notes.append(section.rstrip())
    return notes


def _number(record: dict) -> int | None:
    identity = record.get("identidad_documental_numero")
    if isinstance(identity, int):
        return identity
    match = re.match(r"\s*0*(\d+)", str(record.get("numero") or ""))
    return int(match.group(1)) if match else None


def _year(record: dict) -> int | None:
    explicit = str(record.get("anio") or "").strip()
    if explicit.isdigit():
        return int(explicit)
    match = re.search(r"-(\d{2}|\d{4})(?:\D|$)", str(record.get("numero") or ""))
    if not match:
        return None
    suffix = match.group(1)
    return int(suffix) if len(suffix) == 4 else 2000 + int(suffix)


def _sources_by_identity(records: list[dict], year: int) -> dict[int, dict]:
    sources: dict[int, dict] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Los registros reconciliados deben ser objetos")
        identity = _number(record)
        if identity is None or _year(record) != year:
            raise ValueError("Registro reconciliado sin identidad o año válido")
        document_id = str(record.get("document_id_consultoria") or "").strip()
        if not document_id or identity in sources:
            raise ValueError("Las identidades reconciliadas son ambiguas")
        sources[identity] = record
    return sources


def load_items(validated_packages: dict[int, dict], source_records: list[dict], year: int) -> list[dict]:
    """Construye tarjetas exclusivamente desde paquetes validados y su inventario reconciliado."""
    if not isinstance(validated_packages, dict):
        raise ValueError("Los paquetes validados deben entregarse como diccionario")
    sources = _sources_by_identity(source_records, year)
    identities = set(validated_packages)
    if identities != set(sources):
        raise ValueError("Las identidades validadas no coinciden con las identidades reconciliadas")
    items = []
    for identity in sorted(identities, reverse=True):
        metadata = validated_packages[identity]
        source = sources[identity]
        if not isinstance(identity, int) or not isinstance(metadata, dict):
            raise ValueError("Paquete validado con identidad o metadata inválida")
        if _number(metadata) != identity or _year(metadata) != year:
            raise ValueError("Paquete validado con identidad documental incoherente")
        if str(metadata.get("document_id_consultoria") or "").strip() != str(source.get("document_id_consultoria") or "").strip():
            raise ValueError("Paquete validado con ID distinto al inventario reconciliado")
        title = str(source.get("titulo") or metadata.get("titulo") or "")
        date = normalize_date(source.get("fecha_documento") or "") or normalize_date(metadata.get("fecha") or "") or "—"
        if is_generic(title, identity, year):
            title = f"Decreto {identity:03d}-{year}"
        else:
            title = short_title(title)
        items.append(
            {
                "number": identity,
                "date": date,
                "title": title,
                "href": f"decreto-{identity:03d}-{year}/",
            }
        )
    return items


def render_year(repo: Path, year: int, validated_packages: dict[int, dict], source_records: list[dict]) -> int:
    """Escribe una portada solo si cada tarjeta procede de una identidad validada."""
    repo = Path(repo).resolve()
    items = load_items(validated_packages, source_records, year)
    
    # Calcular rango de fechas
    dates = []
    for identity, metadata in validated_packages.items():
        date_str = normalize_date(metadata.get("fecha") or "")
        if date_str and date_str != "—":
            dates.append(date_str)
    
    date_range = ""
    if dates:
        dates_sorted = sorted(dates, key=lambda d: tuple(int(x) for x in d.split("/")[::-1]))
        first_date = dates_sorted[0]
        last_date = dates_sorted[-1]
        if first_date == last_date:
            date_range = f'<span class="leydo-year-chip">Actualizado al {esc(last_date)}</span>'
        else:
            date_range = f'<span class="leydo-year-chip">Actualizado del {esc(first_date)} al {esc(last_date)}</span>'
    
    index_path = repo / f"docs/decretos/{year}/index.md"
    existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    notes = extract_notes(existing)
    lines = [
        f"# Decretos {year}",
        "",
        '<div class="leydo-year-hero" markdown>',
        f'<p class="leydo-year-kicker">Decretos · {year}</p>',
        "",
        f"Año **{year}**. Lista única: cada decreto aparece **una sola vez**. Pulse una fila para abrir el documento.",
        "",
        f'<div class="leydo-year-summary"><span class="leydo-year-chip"><strong>{len(items)}</strong> decretos</span>{date_range}</div>',
        "</div>",
        "",
        '!!! warning "Aviso"',
        "    LEY.DO no es una fuente oficial. Verifique cada documento contra su fuente oficial.",
        "",
    ]
    if notes:
        lines.extend(notes)
        lines.append("")
    lines.append('<div class="leydo-doclist">')
    for item in items:
        lines.extend(
            [
                f'<a class="leydo-doc" href="{item["href"]}">',
                f'<span class="leydo-doc-num">{item["number"]:03d}-{year}</span>',
                f'<span class="leydo-doc-date">{esc(item["date"])}</span>',
                f'<span class="leydo-doc-title">{esc(item["title"])}</span>',
                "</a>",
            ]
        )
    lines.extend(["</div>", ""])
    index_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(index_path, "\n".join(lines) + "\n")
    return len(items)


def render_hub(repo: Path, year_counts: dict[int, int]) -> int:
    """Escribe el índice general desde conteos explícitos ya revisados."""
    rows = sorted((int(year), int(count)) for year, count in year_counts.items())
    total = sum(count for _, count in rows)
    lines = [
        "# Decretos",
        "",
        '<div class="leydo-year-hero" markdown>',
        '<p class="leydo-year-kicker">Corpus de decretos</p>',
        "",
        "Elija un año. Cada año abre una lista única: un encapsulado por decreto.",
        "",
        f'<div class="leydo-year-summary"><span class="leydo-year-chip"><strong>{total}</strong> decretos en LEY.DO</span></div>',
        "</div>",
        "",
        '!!! warning "Aviso"',
        "    LEY.DO no es una fuente oficial. No certifica exhaustividad, vigencia ni validez legal.",
        "",
        '<div class="leydo-doclist">',
    ]
    for year, count in rows:
        lines.extend(
            [
                f'<a class="leydo-doc" href="{year}/">',
                f'<span class="leydo-doc-num">{year}</span>',
                f'<span class="leydo-doc-date">{count}</span>',
                f'<span class="leydo-doc-title">Ver decretos de {year}</span>',
                "</a>",
            ]
        )
    lines.extend(["</div>", ""])
    _atomic_write_text(Path(repo).resolve() / "docs/decretos/index.md", "\n".join(lines) + "\n")
    return total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--inventario", type=Path, required=True, help="Inventario reconciliado del año a regenerar")
    parser.add_argument("--anio", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        from scripts.procesar_decretos_consultoria import generate_index
        index = generate_index(args.repo.resolve(), args.inventario.resolve(), args.anio)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    count = index.read_text(encoding="utf-8").count('<a class="leydo-doc"')
    print(f"OK {args.anio}: {count} encapsulados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
