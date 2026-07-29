#!/usr/bin/env python3
"""Descarga y normaliza lotes de decretos oficiales de Consultoría Jurídica."""

import argparse
import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def download_pdf(url,destination,opener=urllib.request.urlopen,timeout=60,retries=3,sleeper=time.sleep):
    request=urllib.request.Request(url,headers={"User-Agent":"LEY.DO-normalizador/1.0"}); data=None
    for attempt in range(retries):
        try:
            with opener(request,timeout=timeout) as response: data=response.read()
            break
        except OSError:
            if attempt+1>=retries: raise
            sleeper(2**attempt)
    if not data or not data.startswith(b"%PDF"):
        raise ValueError(f"La fuente no devolvió un PDF válido: {url}")
    destination=Path(destination); destination.parent.mkdir(parents=True,exist_ok=True); temporary=destination.with_suffix(destination.suffix+".tmp")
    temporary.write_bytes(data); temporary.replace(destination)
    return hashlib.sha256(data).hexdigest()


def parse_numbers(spec):
    numbers = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = (int(x) for x in part.split("-", 1))
            numbers.update(range(start, end + 1))
        else:
            numbers.add(int(part))
    return sorted(numbers)

def _numero(record):
    raw=str(record.get("numero", "")); head=raw.split("-",1)[0].strip()
    return int(head) if head.isdigit() else None


def process_documents(repo,inventario_path,year,numbers,downloader=download_pdf,normalizer=None):
    repo=Path(repo); inventario_path=Path(inventario_path)
    records=json.loads(inventario_path.read_text(encoding="utf-8"))["documentos"]["decretos"]
    by_number={}
    for record in records:
        number=_numero(record)
        if number is not None: by_number.setdefault(number,[]).append(record)
    if normalizer is None:
        from scripts.normalizar_decretos_consultoria import run as normalizer
    result={"ok":[],"errors":[]}
    for number in numbers:
        try:
            candidates=by_number.get(number,[])
            if len(candidates)!=1:
                raise ValueError(f"Se esperaban 1 registro para {number}; encontrados: {len(candidates)}")
            record=candidates[0]; stem=f"decreto-{number:03d}-{year}"
            canonical=repo/f"archivos/decretos/{year}/{stem}.pdf"
            if not canonical.is_file() or not canonical.read_bytes().startswith(b"%PDF"):
                downloader(record["url_documento_consultoria_descargar"],canonical)
            for rendition in record.get("rendiciones_oficiales_relacionadas",[]):
                path=repo/rendition["ruta_pdf_local"]
                if not path.is_file() or not path.read_bytes().startswith(b"%PDF"):
                    digest=downloader(rendition["url_pdf_oficial"],path)
                else:
                    digest=hashlib.sha256(path.read_bytes()).hexdigest()
                expected=rendition.get("sha256_pdf","")
                if expected and digest!=expected:
                    raise ValueError(f"Hash inesperado para la rendición {path}")
            normalizer(repo,year,[number],documentos_explicitos={number:record["document_id_consultoria"]},inventario_path=inventario_path)
            result["ok"].append(number)
        except Exception as exc:
            result["errors"].append({"numero":number,"error":str(exc)})
    return result

def _cell(value):
    return str(value or "").replace("|","\|").replace("\n"," ").strip()


def generate_index(repo,inventario_path,year):
    repo=Path(repo); inventario_path=Path(inventario_path); inventory=json.loads(inventario_path.read_text(encoding="utf-8"))
    records=inventory.get("registros_fuente",[]); summary=inventory.get("resumen",{})
    packages=list((repo/f"datos/decretos/{year}").glob(f"decreto-*-{year}.json")) if (repo/f"datos/decretos/{year}").exists() else []
    lines=[f"# Decretos de {year}","","!!! warning \"Aviso\"","    LEY.DO no es una fuente oficial. Verifique cada documento contra la fuente oficial indicada.","    LEY.DO no ofrece asesoría legal.","","## Cobertura","",f"- Registros preservados del inventario oficial reconciliado: {summary.get('registros_fuente',len(records))}.",f"- Identidades documentales normalizadas: {len(packages)} de {summary.get('identidades_documentales','')}.","- Estado editorial: pendiente de revisión humana.","","Los registros repetidos, atípicos o contextuales se conservan como filas independientes para mantener su trazabilidad. La ausencia de un número en este inventario no determina su inexistencia jurídica.","","## Inventario oficial reconciliado","","| Número en fuente | Documento relacionado | Título en fuente | Fecha | Gaceta | Registro oficial | Estado |","|---|---|---|---|---|---|---|"]
    for record in records:
        identity=record.get("identidad_documental_numero"); package=None; related=""
        if isinstance(identity,int):
            package=repo/f"datos/decretos/{year}/decreto-{identity:03d}-{year}.json"
            if package.is_file(): related=f"[Decreto {identity:03d}-{year}](decreto-{identity:03d}-{year}.md)"
        role=record.get("rol_reconciliacion","")
        if role=="rendicion_complementaria": state="rendición oficial relacionada · pendiente_revision"
        elif role=="fuente_contextual_no_decreto": state="fuente contextual oficial · pendiente_revision"
        elif package and package.is_file():
            metadata=json.loads(package.read_text(encoding="utf-8")); state="normalizado con alerta · pendiente_revision" if metadata.get("alertas_revision") else "normalizado · pendiente_revision"
        else: state="descubierto · pendiente_revision"
        document_id=_cell(record.get("document_id_consultoria")); official=_cell(record.get("url_documento_consultoria_abrir")); source=f"[ID {document_id}]({official})" if official else f"ID {document_id}"
        lines.append("| "+" | ".join([f"`{_cell(record.get('numero'))}`",related,_cell(record.get("titulo")),_cell(record.get("fecha_documento")),_cell(record.get("gaceta_oficial")),source,state])+" |")
    destination=repo/f"docs/decretos/{year}/index.md"; destination.parent.mkdir(parents=True,exist_ok=True); destination.write_text("\n".join(lines)+"\n",encoding="utf-8",newline="\n")
    return destination


def main(argv=None,processor=process_documents):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo",required=True,type=Path)
    parser.add_argument("--inventario",required=True,type=Path)
    parser.add_argument("--anio",required=True,type=int)
    parser.add_argument("--numeros",required=True)
    parser.add_argument("--manifiesto",required=True,type=Path)
    args=parser.parse_args(argv); numbers=parse_numbers(args.numeros)
    result=processor(args.repo,args.inventario,args.anio,numbers)
    generate_index(args.repo,args.inventario,args.anio)
    payload={"schema_version":"1.0","fecha_ejecucion":datetime.now(timezone.utc).isoformat(),"anio":args.anio,"inventario":str(args.inventario),"numeros":numbers,"estado":"completado" if not result["errors"] else "completado_con_errores","resultado":result}
    args.manifiesto.parent.mkdir(parents=True,exist_ok=True)
    args.manifiesto.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    return 0 if not result["errors"] else 1


if __name__=="__main__":
    raise SystemExit(main())
