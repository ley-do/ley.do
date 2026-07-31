#!/usr/bin/env python3
"""Regenera portadas anuales de decretos con la plantilla de encapsulados (modelo 2026)."""

from __future__ import annotations

import argparse
import html
import json
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
    s = " ".join(str(value or "").split())
    if not s:
        return ""
    if "|" in s:
        s = s.split("|", 1)[0].strip()
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return s
    m = re.fullmatch(r"(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+(\d{4})", s, re.I)
    if m:
        day = int(m.group(1))
        month = MESES.get(m.group(2).lower())
        year = int(m.group(3))
        if month:
            return f"{day:02d}/{month:02d}/{year}"
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s)
    if m:
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{int(m.group(3))}"
    return s


def short_title(title: str, limit: int = 160) -> str:
    text = " ".join(str(title or "").split())
    text = re.sub(r"^(decreto\s+n[uú]m\.?\s*\d+[\w.-]*\s*[,:-]?\s*)", "", text, flags=re.I).strip()
    letters = re.sub(r"[^A-Za-zÁÉÍÓÚÜáéíóúñÑ]", "", text)
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.8 and len(letters) > 12:
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
    yy = str(year)[-2:]
    return bool(re.fullmatch(rf"Decreto\s*n[uú]m\.?\s*0*{number}(?:-{year}|-{yy})?", text, flags=re.I))


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


def load_inventory(repo: Path, year: int) -> dict[int, dict]:
    path = repo / f"fuentes/consultoria_inventario_{year}_leyes_decretos.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    by: dict[int, dict] = {}
    for record in data.get("documentos", {}).get("decretos", []):
        match = re.match(r"\s*0*(\d+)", str(record.get("numero") or ""))
        if match:
            by[int(match.group(1))] = record
    return by


def load_items(repo: Path, year: int) -> list[dict]:
    inventory = load_inventory(repo, year)
    items = []
    root = repo / f"datos/decretos/{year}"
    if not root.exists():
        return items
    for path in sorted(root.glob(f"decreto-*-{year}.json")):
        match = re.fullmatch(rf"decreto-(\d+)-{year}\.json", path.name)
        if not match:
            continue
        number = int(match.group(1))
        markdown = repo / f"docs/decretos/{year}/decreto-{number:03d}-{year}.md"
        if not markdown.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        title = data.get("titulo") or ""
        date = data.get("fecha") or ""
        source = inventory.get(number) or {}
        if is_generic(title, number, year):
            title = source.get("titulo") or title
        date = normalize_date(date) or normalize_date(source.get("fecha_documento") or "") or "—"
        if is_generic(title, number, year) or not title:
            title = f"Decreto {number:03d}-{year}"
        else:
            title = short_title(title)
        items.append(
            {
                "number": number,
                "date": date,
                "title": title,
                # Public MkDocs path (never .md in raw HTML hrefs).
                "href": f"decreto-{number:03d}-{year}/",
            }
        )
    return items


def render_year(repo: Path, year: int) -> int:
    items = load_items(repo, year)
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
        f'<div class="leydo-year-summary"><span class="leydo-year-chip"><strong>{len(items)}</strong> decretos</span></div>',
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


def render_hub(repo: Path) -> int:
    rows = []
    total = 0
    for year in range(2016, 2027):
        count = len(load_items(repo, year))
        total += count
        rows.append((year, count))
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
    _atomic_write_text(repo / "docs/decretos/index.md", "\n".join(lines) + "\n")
    return total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--inicio", type=int, default=2016)
    parser.add_argument("--fin", type=int, default=2026)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    for year in range(args.inicio, args.fin + 1):
        count = render_year(repo, year)
        print(f"OK {year}: {count} encapsulados")
    total = render_hub(repo)
    print(f"OK hub: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
