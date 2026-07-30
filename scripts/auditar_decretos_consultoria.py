#!/usr/bin/env python3
"""Audita un corpus anual de decretos normalizados por LEY.DO sin interpretar su contenido legal."""

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path

import fitz

try:
    from scripts.normalizar_decretos_consultoria import extract
    from scripts.procesar_decretos_consultoria import _atomic_write_text,_hash_file,_pending_evidence,_safe_repo_path,_validated_packages
except ModuleNotFoundError:
    from normalizar_decretos_consultoria import extract
    from procesar_decretos_consultoria import _atomic_write_text,_hash_file,_pending_evidence,_safe_repo_path,_validated_packages

DATE_RE=re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
FORMAL_RE=re.compile(r"(?im)^N[ÚU]MERO:\s*(\d+)\s*-\s*(\d{2}|\d{4})\b")
MONTHS={"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,"julio":7,"agosto":8,"septiembre":9,"setiembre":9,"octubre":10,"noviembre":11,"diciembre":12}


def _number(record):
    value=record.get("identidad_documental_numero")
    if isinstance(value,int): return value
    match=re.match(r"\s*0*(\d+)",str(record.get("numero") or ""))
    return int(match.group(1)) if match else None


def _year(record):
    number=str(record.get("numero") or "")
    match=re.search(r"-(\d{2}|\d{4})(?:\D|$)",number)
    if match:
        value=match.group(1); return int(value) if len(value)==4 else 2000+int(value)
    try: return int(record.get("anio"))
    except (TypeError,ValueError): return None


def _read_pdf_evidence(pdf_path,number,year):
    pages,*_=extract(pdf_path,number,str(year)[-2:]); text="\n".join(pages)
    match=FORMAL_RE.search(text)
    formal=("",None,None) if not match else (f"{int(match.group(1))}-{match.group(2)}",int(match.group(1)),match.group(2))
    markers=list(re.finditer(r"\bDAD[OA]\b",text,re.I))
    if not markers: return (*formal,"","clausula_dado_no_detectada")
    snippet=text[markers[-1].start():markers[-1].start()+900]
    month=re.search(r"\b("+"|".join(MONTHS)+r")\b",snippet,re.I)
    if not month: return (*formal,"","clausula_dado_no_parseable")
    days=[int(value) for value in re.findall(r"\(\s*(\d{1,2})(?:\s*\)|(?:er\.)?\s*\))",snippet[:month.start()],re.I)]
    years=[int(value) for value in re.findall(r"(?:\(\s*)?(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)(?:\s*\))?",snippet[month.end():])]
    if not days or not years: return (*formal,"","clausula_dado_no_parseable")
    day=days[-1]; month_number=MONTHS[month.group(1).lower()]; observed_year=years[0]
    try: datetime(observed_year,month_number,day)
    except ValueError: return (*formal,"","clausula_dado_no_parseable")
    return (*formal,f"{day:02d}/{month_number:02d}/{observed_year}","detectada")


def audit(repo,inventory_path,year):
    repo=Path(repo).resolve(); resolved=Path(inventory_path).resolve(); errors=[]; warnings=[]
    try: relative=resolved.relative_to(repo); inventory_path=_safe_repo_path(repo,relative,allowed_root=repo)
    except ValueError as exc: raise ValueError(f"Inventario fuera del repositorio: {inventory_path}") from exc
    inventory=json.loads(inventory_path.read_text(encoding="utf-8")); source_records=inventory.get("registros_fuente",[]); canonical=[record for record in inventory.get("documentos",{}).get("decretos",[]) if _year(record)==year]
    source_ids=[]
    for record in source_records:
        value=str(record.get("document_id_consultoria") or "").strip()
        if not value: errors.append("Registro fuente sin document_id_consultoria")
        source_ids.append(value)
    if len(source_ids)!=len(set(source_ids)): errors.append("Hay IDs duplicados en registros_fuente")
    identities=[_number(record) for record in canonical]; canonical_ids=[str(record.get("document_id_consultoria") or "").strip() for record in canonical]
    if None in identities: errors.append("Hay identidades documentales sin número")
    if len(identities)!=len(set(identities)): errors.append("Hay identidades documentales duplicadas")
    if len(canonical_ids)!=len(set(canonical_ids)): errors.append("Hay IDs canónicos duplicados")
    summary_source=inventory.get("resumen",{}).get("total_registros_fuente")
    summary_canonical=inventory.get("resumen",{}).get("total_identidades_documentales")
    if summary_source is not None and int(summary_source)!=len(source_records): errors.append("El resumen del inventario no coincide con registros_fuente")
    if summary_canonical is not None and int(summary_canonical)!=len(canonical): errors.append("El resumen del inventario no coincide con las identidades documentales")
    try: validated=_validated_packages(repo,inventory,year)
    except ValueError as exc: validated={}; errors.append(str(exc))
    missing_packages=sorted(set(identities)-set(validated))
    if missing_packages: errors.append(f"Paquetes ausentes, obsoletos o inconsistentes: {missing_packages}")
    pdf_root=repo/f"archivos/decretos/{year}"; md_root=repo/f"docs/decretos/{year}"; data_root=repo/f"datos/decretos/{year}"
    _safe_repo_path(repo,f"archivos/decretos/{year}",allowed_root=pdf_root); _safe_repo_path(repo,f"docs/decretos/{year}",allowed_root=md_root); _safe_repo_path(repo,f"datos/decretos/{year}",allowed_root=data_root)
    expected_pdfs=set(); expected_md=set(); expected_json=set(); special_renditions={}
    record_by_number={_number(record):record for record in canonical}
    for number,record in record_by_number.items():
        stem=f"decreto-{number:03d}-{year}"
        if record.get("estado_extraccion")!="pendiente_encontrar_pdf": expected_pdfs.add(f"archivos/decretos/{year}/{stem}.pdf")
        expected_md.add(f"docs/decretos/{year}/{stem}.md"); expected_json.add(f"datos/decretos/{year}/{stem}.json")
        renditions=[]
        for item in record.get("rendiciones_oficiales_relacionadas",[]):
            path=_safe_repo_path(repo,item.get("ruta_pdf_local",""),allowed_root=pdf_root).relative_to(repo).as_posix(); expected_pdfs.add(path); renditions.append(path)
        if renditions: special_renditions[str(number)]=renditions
    actual_pdfs={p.relative_to(repo).as_posix() for p in pdf_root.glob("decreto-*.pdf")} if pdf_root.exists() else set(); actual_md={p.relative_to(repo).as_posix() for p in md_root.glob("decreto-*.md")} if md_root.exists() else set(); actual_json={p.relative_to(repo).as_posix() for p in data_root.glob("decreto-*.json")} if data_root.exists() else set()
    for label,expected,actual in (("PDF",expected_pdfs,actual_pdfs),("Markdown",expected_md,actual_md),("JSON",expected_json,actual_json)):
        missing=sorted(expected-actual); extra=sorted(actual-expected)
        if missing: errors.append(f"{label} faltantes: {missing}")
        if extra: errors.append(f"{label} huérfanos: {extra}")
    date_discrepancies=[]; no_dado=[]; documented_unparseable=[]; no_formal=[]; formal_discrepancies=[]; neighbor_fragments=[]; pending_documents=[]; hash_groups=defaultdict(list)
    for number in sorted(record_by_number):
        metadata_path=data_root/f"decreto-{number:03d}-{year}.json"
        try: metadata=json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError): continue
        alerts=metadata.get("alertas_revision") if isinstance(metadata.get("alertas_revision"),list) else []; alert_text=" ".join(str(item) for item in alerts).lower()
        source_record=record_by_number[number]
        source_date=str(source_record.get("fecha_documento") or "").strip(); metadata_date=str(metadata.get("fecha") or "").strip()
        if metadata_date!=source_date:
            errors.append(f"Decreto {number}: fecha del JSON no coincide con la fuente reconciliada (JSON: {metadata_date!r}; fuente: {source_date!r})")
        source_gaceta=str(source_record.get("gaceta_oficial") or "").strip(); metadata_gaceta=str(metadata.get("gaceta_oficial") or "").strip()
        if metadata_gaceta!=source_gaceta:
            errors.append(f"Decreto {number}: Gaceta del JSON no coincide con la fuente reconciliada (JSON: {metadata_gaceta!r}; fuente: {source_gaceta!r})")
        pdf_path=pdf_root/f"decreto-{number:03d}-{year}.pdf"
        if source_record.get("estado_extraccion")=="pendiente_encontrar_pdf":
            try: evidence=_pending_evidence(source_record)
            except ValueError as exc: errors.append(f"Decreto {number}: pendiente de PDF inválido: {exc}"); continue
            if metadata.get("estado_extraccion")!="pendiente_encontrar_pdf" or metadata.get("estado_publicacion")!="descubierto": errors.append(f"Decreto {number}: estado pendiente no conservado en el paquete")
            if metadata.get("evidencia_pdf_no_disponible")!=evidence: errors.append(f"Decreto {number}: evidencia de PDF no disponible no coincide con la fuente reconciliada")
            if metadata.get("ruta_pdf_local") or metadata.get("sha256_pdf_original") or pdf_path.exists(): errors.append(f"Decreto {number}: un pendiente_encontrar_pdf no puede presentar PDF local ni hash")
            if not alerts: errors.append(f"Decreto {number}: pendiente_encontrar_pdf sin alerta")
            pending_documents.append(number)
            continue
        try: formal_text,formal_number,formal_year,pdf_observed,pdf_state=_read_pdf_evidence(pdf_path,number,year)
        except Exception as exc: errors.append(f"Decreto {number}: no se pudo verificar la evidencia del PDF: {exc}"); continue
        state=metadata.get("estado_fecha_texto_pdf"); observed=str(metadata.get("fecha_texto_pdf_detectada") or "")
        if state!=pdf_state or observed!=pdf_observed:
            errors.append(f"Decreto {number}: DADO del JSON no coincide con el PDF (JSON: {state} {observed}; PDF: {pdf_state} {pdf_observed})")
        if state=="detectada":
            match=DATE_RE.match(observed)
            try: datetime.strptime(observed,"%d/%m/%Y")
            except ValueError: match=None
            if not match: errors.append(f"Decreto {number}: fecha DADO detectada inválida: {observed}")
            elif int(match.group(3))!=year and not (metadata.get("fecha_metadata_fuente") and alerts):
                errors.append(f"Decreto {number}: año DADO observado distinto sin discrepancia documentada: {observed}")
        elif state=="clausula_dado_no_parseable":
            no_dado.append(number)
            if alerts: documented_unparseable.append(number)
            else: errors.append(f"Decreto {number}: DADO no parseable sin alerta")
        else: errors.append(f"Decreto {number}: estado_fecha_texto_pdf inválido: {state}")
        if metadata.get("fecha_metadata_fuente"):
            date_discrepancies.append(number)
            if not alerts: errors.append(f"Decreto {number}: discrepancia de fecha sin alerta")
        fragments=metadata.get("fragmentos_decretos_vecinos_excluidos")
        if not isinstance(fragments,list): errors.append(f"Decreto {number}: fragmentos vecinos no documentados")
        else: neighbor_fragments.append({"numero":number,"fragmentos":fragments})
        if pdf_path.is_file(): hash_groups[_hash_file(pdf_path)].append(number)
        if not formal_text:
            no_formal.append(number); continue
        if formal_year not in {str(year),str(year)[-2:]}: errors.append(f"Decreto {number}: año formal {formal_year} no corresponde a {year}")
        if str(metadata.get("numero_formal_pdf") or "")!=formal_text: errors.append(f"Decreto {number}: numero_formal_pdf no conserva {formal_text}")
        if formal_number!=number:
            formal_discrepancies.append({"numero":number,"numero_formal_pdf":formal_text})
            if "línea formal" not in alert_text: errors.append(f"Decreto {number}: discrepancia formal {formal_text} sin alerta")
    duplicate_hashes=[{"sha256":digest,"numeros":numbers} for digest,numbers in sorted(hash_groups.items()) if len(numbers)>1]
    if duplicate_hashes: errors.append("Hay PDFs canónicos distintos con hash repetido")
    index_path=_safe_repo_path(repo,f"docs/decretos/{year}/index.md",allowed_root=md_root)
    try: index_content=index_path.read_text(encoding="utf-8")
    except OSError: index_content=""; errors.append("Falta el índice anual")
    index_rows=[line for line in index_content.splitlines() if line.startswith("| `")]; index_ids=re.findall(r"\[ID ([^\]]+)\]",index_content)
    if len(index_rows)!=len(source_records): errors.append(f"Filas del índice: {len(index_rows)}; esperadas: {len(source_records)}")
    if len(index_ids)!=len(source_records) or len(set(index_ids))!=len(source_records): errors.append("Los IDs del índice no son completos y únicos")
    report={
        "schema_version":"1.1","fecha_auditoria":datetime.now(timezone.utc).isoformat(),"anio":year,
        "fuente_reconciliada":inventory_path.relative_to(repo).as_posix(),"sha256_fuente_reconciliada":_hash_file(inventory_path),
        "resumen":{"registros_fuente":len(source_records),"identidades_documentales":len(canonical),"pdfs_locales":len(actual_pdfs),"markdown":len(actual_md),"json":len(actual_json),"filas_indice":len(index_rows),"ids_indice_unicos":len(set(index_ids)),"paquetes_validados":len(validated),"documentos_con_fragmentos_vecinos_delimitados":len(neighbor_fragments),"discrepancias_fecha_documentadas":len(date_discrepancies),"documentos_sin_fecha_dado_detectable":len(no_dado),"documentos_fecha_no_parseable_con_alerta":len(documented_unparseable),"documentos_sin_linea_formal_numero_detectable":len(no_formal),"discrepancias_numero_formal_documentadas":len(formal_discrepancies),"documentos_pendientes_encontrar_pdf":len(pending_documents),"grupos_pdf_canonicos_con_hash_repetido":len(duplicate_hashes),"errores":len(errors),"advertencias":len(warnings)},
        "discrepancias_fecha":date_discrepancies,"documentos_pendientes_encontrar_pdf":pending_documents,"documentos_sin_fecha_dado_detectable":no_dado,"fechas_no_parseables_documentadas":documented_unparseable,"documentos_sin_linea_formal_numero_detectable":no_formal,"discrepancias_numero_formal":formal_discrepancies,"fragmentos_vecinos_delimitados":neighbor_fragments,"grupos_pdf_canonicos_con_hash_repetido":duplicate_hashes,"rendiciones_especiales":special_renditions,"advertencias":warnings,"errores":errors,
    }
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--repo",required=True,type=Path); parser.add_argument("--inventario",required=True,type=Path); parser.add_argument("--anio",required=True,type=int); parser.add_argument("--salida",type=Path); args=parser.parse_args(argv)
    try: report=audit(args.repo,args.inventario,args.anio)
    except Exception as exc: print(f"ERROR: {exc}"); return 1
    output=args.salida or Path(args.repo)/"fuentes"/f"decretos_{args.anio}_auditoria.json"; repo=Path(args.repo).resolve()
    try: relative=output.resolve().relative_to(repo); destination=_safe_repo_path(repo,relative,allowed_root=repo)
    except ValueError as exc: print(f"ERROR: {exc}"); return 1
    _atomic_write_text(destination,json.dumps(report,ensure_ascii=False,indent=2)+"\n"); print(json.dumps(report["resumen"],ensure_ascii=False)); return 1 if report["errores"] else 0


if __name__=="__main__": raise SystemExit(main())
