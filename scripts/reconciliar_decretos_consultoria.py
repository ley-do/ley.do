#!/usr/bin/env python3
"""Reconcilia identidades documentales de decretos de Consultoría Jurídica."""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path, PurePosixPath

try:
    from scripts.procesar_decretos_consultoria import _atomic_write_text, _hash_file
except ModuleNotFoundError:
    from procesar_decretos_consultoria import _atomic_write_text, _hash_file

_NUMBER_RE = re.compile(r"^\s*0*(\d+)\s*-\s*(\d{2}|\d{4})\s*$")
_LEADING_NUMBER_RE = re.compile(r"^\s*0*(\d+)\b")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _parse_number(value):
    match = _NUMBER_RE.fullmatch(str(value or ""))
    if not match:
        return None
    suffix = int(match.group(2))
    parsed_year = suffix if suffix >= 1000 else 2000 + suffix
    return int(match.group(1)), parsed_year


def _validate_renditions(year, number, canonical_id, group_by_id, renditions):
    if not isinstance(renditions, list) or not renditions:
        return [], ""
    seen = set()
    validated = []
    canonical_hash = ""
    canonical_path = f"archivos/decretos/{year}/decreto-{number:03d}-{year}.pdf"
    for rendition in renditions:
        if not isinstance(rendition, dict):
            raise ValueError(f"Rendición inválida para identidad {number}")
        item = copy.deepcopy(rendition)
        document_id = str(item.get("document_id_consultoria") or "").strip()
        if not document_id or document_id in seen:
            raise ValueError(f"ID de rendición vacío o duplicado para identidad {number}: {document_id!r}")
        seen.add(document_id)
        source = group_by_id.get(document_id)
        if source is None:
            raise ValueError(f"Rendición {document_id} no pertenece a la identidad {number}")
        source_url = str(source.get("url_documento_consultoria_descargar") or "").strip()
        official_url = str(item.get("url_pdf_oficial") or "").strip()
        if official_url != source_url:
            raise ValueError(f"URL de rendición no coincide con fuente para ID {document_id}")
        digest = str(item.get("sha256_pdf") or "").strip().lower()
        if not _SHA256_RE.fullmatch(digest):
            raise ValueError(f"SHA256 inválido para rendición {document_id}")
        item["sha256_pdf"] = digest
        role = str(item.get("rol_archivistico") or "").strip()
        if not role:
            raise ValueError(f"Rol archivístico faltante para rendición {document_id}")
        local_path = str(item.get("ruta_pdf_local") or "").replace("\\", "/")
        pure = PurePosixPath(local_path)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"Ruta de rendición no confinada para ID {document_id}")
        expected_root = PurePosixPath(f"archivos/decretos/{year}")
        if pure.parent != expected_root:
            raise ValueError(f"Ruta de rendición fuera de la raíz anual para ID {document_id}")
        if document_id == canonical_id:
            if local_path != canonical_path:
                raise ValueError(f"Ruta canónica incorrecta para ID {document_id}")
            canonical_hash = digest
        else:
            expected = f"decreto-{number:03d}-{year}-fuente-{document_id}.pdf"
            if pure.name != expected:
                raise ValueError(f"Ruta complementaria no canónica para ID {document_id}")
        pages = item.get("paginas")
        if not isinstance(pages, int) or pages <= 0:
            raise ValueError(f"Conteo de páginas inválido para rendición {document_id}")
        if not isinstance(item.get("capa_texto"), bool):
            raise ValueError(f"Indicador de capa de texto inválido para rendición {document_id}")
        validated.append(item)
    if canonical_id not in seen:
        raise ValueError(f"Las rendiciones de identidad {number} no incluyen el PDF canónico {canonical_id}")
    return validated, canonical_hash


def reconcile(inventory, year, decisions, inventory_name=None):
    if not isinstance(inventory, dict) or not isinstance(decisions, dict):
        raise ValueError("Inventario y decisiones deben ser objetos JSON")
    year = int(year)
    if decisions.get("schema_version") != "1.0":
        raise ValueError("schema_version de decisiones incompatible; se requiere 1.0")
    reconciliation_date = decisions.get("fecha_reconciliacion")
    if not isinstance(reconciliation_date, str):
        raise ValueError("fecha_reconciliacion debe usar formato ISO YYYY-MM-DD")
    try:
        parsed_reconciliation_date = date.fromisoformat(reconciliation_date)
    except ValueError as exc:
        raise ValueError("fecha_reconciliacion debe usar formato ISO YYYY-MM-DD") from exc
    if parsed_reconciliation_date.isoformat() != reconciliation_date:
        raise ValueError("fecha_reconciliacion debe usar formato ISO YYYY-MM-DD")
    decision_year = decisions.get("anio")
    if decision_year not in (None, year, str(year)):
        raise ValueError(f"El alcance de decisiones no coincide con {year}")
    rows = inventory.get("documentos", {}).get("decretos")
    if not isinstance(rows, list):
        raise ValueError("El inventario no contiene documentos.decretos")
    source_name = inventory_name or f"consultoria_inventario_{year}_leyes_decretos.json"
    ids = [str(row.get("document_id_consultoria") or "").strip() for row in rows]
    if any(not item for item in ids):
        raise ValueError("Hay registros fuente sin document_id_consultoria")
    duplicates = [item for item, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"IDs de Consultoría duplicados: {duplicates}")

    identity_decisions = decisions.get("identidades", {})
    context_decisions = decisions.get("fuentes_contextuales", {})
    if not isinstance(identity_decisions, dict) or not isinstance(context_decisions, dict):
        raise ValueError("identidades y fuentes_contextuales deben ser objetos")
    unknown_context = set(map(str, context_decisions)) - set(ids)
    if unknown_context:
        raise ValueError(f"Decisiones contextuales para IDs inexistentes: {sorted(unknown_context)}")
    assigned_identity_ids = set()
    for identity, decision in identity_decisions.items():
        if not isinstance(decision, dict):
            raise ValueError(f"Decisión inválida para identidad {identity}")
        canonical_id = str(decision.get("canonico") or "").strip()
        if canonical_id:
            assigned_identity_ids.add(canonical_id)
        renditions = decision.get("rendiciones", [])
        if not isinstance(renditions, list):
            raise ValueError(f"Rendiciones inválidas para identidad {identity}")
        for rendition in renditions:
            if not isinstance(rendition, dict):
                raise ValueError(f"Rendición inválida para identidad {identity}")
            rendition_id = str(rendition.get("document_id_consultoria") or "").strip()
            if rendition_id:
                assigned_identity_ids.add(rendition_id)
    contradictory_ids = assigned_identity_ids & set(map(str, context_decisions))
    if contradictory_ids:
        raise ValueError(f"Clasificación contradictoria para IDs: {sorted(contradictory_ids)}")

    groups = defaultdict(list)
    outside = []
    for row in rows:
        parsed = _parse_number(row.get("numero"))
        if parsed and parsed[1] == year:
            groups[parsed[0]].append(row)
        else:
            outside.append((row, parsed))
    unknown_numbers = set(map(str, identity_decisions)) - {str(number) for number in groups}
    if unknown_numbers:
        raise ValueError(f"Decisiones para identidades inexistentes: {sorted(unknown_numbers)}")

    source_rows = []
    source_by_id = {}
    for row in rows:
        item = copy.deepcopy(row)
        item["inventario_origen"] = source_name
        source_rows.append(item)
        source_by_id[str(item["document_id_consultoria"])] = item

    canonicals = []
    additional_renditions = 0
    linked_records = 0
    for number in sorted(groups):
        group = groups[number]
        group_by_id = {str(row["document_id_consultoria"]): row for row in group}
        decision = identity_decisions.get(str(number), {})
        if not isinstance(decision, dict):
            raise ValueError(f"Decisión inválida para identidad {number}")
        if len(group) > 1 and not decision:
            raise ValueError(f"Falta decisión explícita para identidad duplicada {number}")
        canonical_id = str(decision.get("canonico") or (group[0]["document_id_consultoria"] if len(group) == 1 else "")).strip()
        if canonical_id not in group_by_id:
            raise ValueError(f"ID canónico inválido para identidad {number}: {canonical_id}")
        renditions, canonical_hash = _validate_renditions(year, number, canonical_id, group_by_id, decision.get("rendiciones", []))
        rendition_ids = {str(item["document_id_consultoria"]) for item in renditions}
        contextual_ids = {str(item) for item in context_decisions if str(item) in group_by_id}
        unresolved = set(group_by_id) - {canonical_id} - rendition_ids - contextual_ids
        if unresolved:
            raise ValueError(f"Registros duplicados sin clasificar para identidad {number}: {sorted(unresolved)}")

        canonical = copy.deepcopy(group_by_id[canonical_id])
        canonical.update({
            "inventario_origen": source_name,
            "identidad_documental_numero": number,
            "rol_reconciliacion": "canonico",
            "numero_registro_fuente": canonical.get("numero", ""),
            "anio_metadata_fuente": str(canonical.get("anio", "")),
        })
        if renditions:
            canonical["rendiciones_oficiales_relacionadas"] = renditions
            canonical["sha256_pdf"] = canonical_hash
            additional_renditions += len(renditions) - 1
        alerts = decision.get("alertas_revision", [])
        if alerts:
            if not isinstance(alerts, list) or any(not isinstance(alert, str) or not alert.strip() for alert in alerts):
                raise ValueError(f"Alertas inválidas para identidad {number}")
            canonical["alertas_revision"] = alerts
        observation = str(decision.get("observacion_reconciliacion") or "").strip()
        if observation:
            canonical["observacion_reconciliacion"] = observation
        canonicals.append(canonical)

        for document_id, original in group_by_id.items():
            source = source_by_id[document_id]
            if document_id == canonical_id:
                source.update({"identidad_documental_numero": number, "rol_reconciliacion": "canonico"})
                linked_records += 1
            elif document_id in rendition_ids:
                source.update({"identidad_documental_numero": number, "rol_reconciliacion": "rendicion_complementaria"})
                linked_records += 1
            else:
                contextual = context_decisions[document_id]
                if not isinstance(contextual, dict):
                    raise ValueError(f"Decisión contextual inválida para ID {document_id}")
                role = str(contextual.get("rol_reconciliacion") or "fuente_contextual_atipica").strip()
                if not role.startswith("fuente_contextual"):
                    raise ValueError(f"Rol contextual inválido para ID {document_id}")
                source["rol_reconciliacion"] = role
                note = str(contextual.get("observacion_reconciliacion") or "").strip()
                if note:
                    source["observacion_reconciliacion"] = note

    for row, parsed in outside:
        document_id = str(row["document_id_consultoria"])
        source = source_by_id[document_id]
        contextual = context_decisions.get(document_id, {})
        if contextual and not isinstance(contextual, dict):
            raise ValueError(f"Decisión contextual inválida para ID {document_id}")
        default_role = "fuente_contextual_fuera_de_anio" if parsed else "fuente_contextual_atipica"
        role = str(contextual.get("rol_reconciliacion") or default_role)
        if not role.startswith("fuente_contextual"):
            raise ValueError(f"Rol contextual inválido para ID {document_id}")
        source["rol_reconciliacion"] = role
        note = str(contextual.get("observacion_reconciliacion") or "").strip()
        if note:
            source["observacion_reconciliacion"] = note

    contextual_count = sum(str(row.get("rol_reconciliacion", "")).startswith("fuente_contextual") for row in source_rows)
    numbers = sorted(groups)
    missing = list(range(numbers[0], numbers[-1] + 1)) if numbers else []
    missing = [number for number in missing if number not in groups]
    summary = {
        "registros_fuente": len(source_rows),
        "total_registros_fuente": len(source_rows),
        "registros_numerados": sum(bool(_LEADING_NUMBER_RE.match(str(row.get("numero") or ""))) for row in rows),
        "identidades_documentales": len(canonicals),
        "total_identidades_documentales": len(canonicals),
        "rendiciones_adicionales": additional_renditions,
        "fuentes_contextuales": contextual_count,
        "numeros_no_detectados_en_secuencia": missing,
        "registros_vinculados_a_identidad": linked_records,
    }
    return {
        "schema_version": "1.0",
        "fecha_reconciliacion": reconciliation_date,
        "institucion_fuente": "Consultoría Jurídica del Poder Ejecutivo",
        "url_fuente_oficial": "https://www.consultoria.gov.do/consulta/",
        "fuentes_inventario": [source_name],
        "resumen": summary,
        "criterios_reconciliacion": [
            f"Solo los números con sufijo documental -{str(year)[-2:]} se consideran identidades del corpus {year}.",
            "Los registros repetidos requieren una decisión explícita por document_id_consultoria.",
            "Las rendiciones oficiales conservan ID, rol, ruta, URL y SHA256 propios.",
            "Los registros atípicos o de otro año se preservan como fuentes contextuales sin reclasificación silenciosa.",
        ],
        "registros_fuente": source_rows,
        "documentos": {"decretos": canonicals},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reconcilia decretos de Consultoría Jurídica por identidad documental")
    parser.add_argument("--inventario", required=True)
    parser.add_argument("--decisiones", required=True)
    parser.add_argument("--anio", required=True, type=int)
    parser.add_argument("--salida", required=True)
    args = parser.parse_args(argv)
    inventory_path = Path(args.inventario)
    decisions_path = Path(args.decisiones)
    destination = Path(args.salida)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    result = reconcile(inventory, args.anio, decisions, inventory_name=inventory_path.name)
    result["sha256_inventario_original"] = _hash_file(inventory_path)
    result["sha256_decisiones_reconciliacion"] = _hash_file(decisions_path)
    _atomic_write_text(destination, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["resumen"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
