#!/usr/bin/env python3
"""Descarga y normaliza lotes de decretos oficiales de Consultoría Jurídica."""

import argparse
import hashlib
import http.client
import html
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pymupdf


OFFICIAL_HOSTS={"consultoria.gov.do","www.consultoria.gov.do"}


def _validate_official_url(url):
    parsed=urllib.parse.urlsplit(str(url))
    if parsed.scheme!="https" or (parsed.hostname or "").lower() not in OFFICIAL_HOSTS or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError(f"URL oficial no permitida: {url}")
    return str(url)


def _markdown_url(url):
    _validate_official_url(url); parsed=urllib.parse.urlsplit(str(url).strip()); host=(parsed.hostname or "").lower(); netloc=host if parsed.port is None else f"{host}:{parsed.port}"
    path=urllib.parse.quote(parsed.path,safe="/%~._-"); query=urllib.parse.quote(parsed.query,safe="=&%~._-+"); fragment=urllib.parse.quote(parsed.fragment,safe="%~._-")
    return urllib.parse.urlunsplit(("https",netloc,path,query,fragment))


def _safe_repo_path(repo,relative_path,allowed_root=None):
    root=Path(repo).resolve(); relative=Path(str(relative_path))
    if relative.is_absolute():
        raise ValueError(f"Ruta fuera del repositorio: {relative_path}")
    lexical=Path(os.path.abspath(root/relative))
    try: lexical_relative=lexical.relative_to(root)
    except ValueError as exc: raise ValueError(f"Ruta fuera del repositorio: {relative_path}") from exc
    allowed=Path(allowed_root) if allowed_root is not None else root
    if not allowed.is_absolute(): allowed=root/allowed
    allowed=Path(os.path.abspath(allowed))
    try: allowed.relative_to(root); lexical.relative_to(allowed)
    except ValueError as exc: raise ValueError(f"Ruta fuera de la raíz permitida: {relative_path}") from exc
    current=root
    for part in lexical_relative.parts:
        current=current/part
        if current.is_symlink():
            raise ValueError(f"Ruta contiene un enlace simbólico no permitido: {relative_path}")
    destination=lexical.resolve(strict=False)
    try: destination.relative_to(root); destination.relative_to(allowed.resolve(strict=False))
    except ValueError as exc: raise ValueError(f"Ruta fuera de la raíz permitida: {relative_path}") from exc
    return destination


def _hash_file(path,chunk_size=1024*1024):
    digest=hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda:handle.read(chunk_size),b""): digest.update(chunk)
    return digest.hexdigest()


def _valid_pdf(path):
    try:
        with Path(path).open("rb") as handle:
            if handle.read(5)!=b"%PDF-": return False
        document=pymupdf.open(path); valid=document.page_count>0; document.close(); return valid
    except (OSError,RuntimeError,ValueError): return False


def download_pdf(url,destination,opener=urllib.request.urlopen,timeout=60,retries=3,sleeper=time.sleep,max_bytes=100*1024*1024,expected_hash=""):
    _validate_official_url(url); destination=Path(destination); destination.parent.mkdir(parents=True,exist_ok=True)
    request=urllib.request.Request(url,headers={"User-Agent":"LEY.DO-normalizador/1.0"}); last_error=None
    for attempt in range(retries):
        temporary=None
        try:
            with opener(request,timeout=timeout) as response:
                final_url=response.geturl() if hasattr(response,"geturl") else url; _validate_official_url(final_url)
                content_length=getattr(response,"headers",{}).get("Content-Length") if hasattr(getattr(response,"headers",{}),"get") else None
                declared_length=int(content_length) if content_length not in (None,"") else None
                if declared_length is not None and (declared_length<0 or declared_length>max_bytes): raise ValueError(f"PDF excede el límite de {max_bytes} bytes")
                with tempfile.NamedTemporaryFile(mode="wb",delete=False,dir=destination.parent,prefix=destination.name+".",suffix=".tmp") as handle:
                    temporary=Path(handle.name); total=0
                    while True:
                        chunk=response.read(min(1024*1024,max_bytes-total+1))
                        if not chunk: break
                        total+=len(chunk)
                        if total>max_bytes: raise ValueError(f"PDF excede el límite de {max_bytes} bytes")
                        handle.write(chunk)
                    if declared_length is not None and total!=declared_length:
                        raise ValueError(f"Content-Length no coincide: declarados {declared_length} bytes, recibidos {total}")
                    handle.flush(); os.fsync(handle.fileno())
            if not _valid_pdf(temporary): raise ValueError(f"La fuente no devolvió un PDF estructuralmente válido: {url}")
            digest=_hash_file(temporary)
            if expected_hash and digest.lower()!=str(expected_hash).lower(): raise ValueError(f"Hash SHA256 inesperado para {url}")
            os.replace(temporary,destination); temporary=None; return digest
        except (OSError,RuntimeError,ValueError,http.client.HTTPException) as exc:
            last_error=exc
            if attempt+1>=retries: raise
            sleeper(2**attempt)
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)
    raise last_error


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


def _anio(record):
    raw=str(record.get("numero") or ""); suffix=raw.rsplit("-",1)[-1].strip() if "-" in raw else ""
    if len(suffix)==2 and suffix.isdigit(): return 2000+int(suffix)
    if len(suffix)==4 and suffix.isdigit(): return int(suffix)
    explicit=str(record.get("anio") or "").strip()
    return int(explicit) if explicit.isdigit() else None


def _pending_evidence(record):
    if record.get("estado_extraccion") != "pendiente_encontrar_pdf":
        return None
    evidence = record.get("evidencia_pdf_no_disponible")
    if not isinstance(evidence, dict) or not str(evidence.get("motivo") or "").strip():
        raise ValueError("evidencia_pdf_no_disponible inválida")
    fragment_ids = evidence.get("document_ids_recortes")
    if not isinstance(fragment_ids, list) or not fragment_ids or any(not str(item).strip() for item in fragment_ids):
        raise ValueError("evidencia_pdf_no_disponible sin document_ids_recortes válidos")
    if evidence.get("pdf_derivado_creado") is not False:
        raise ValueError("Un pendiente_encontrar_pdf debe confirmar pdf_derivado_creado=false")
    if record.get("rendiciones_oficiales_relacionadas"):
        raise ValueError("Un pendiente_encontrar_pdf no puede declarar rendiciones completas")
    return evidence


def _write_pending_package(repo,year,number,record):
    repo=Path(repo).resolve(); evidence=_pending_evidence(record)
    if evidence is None:
        raise ValueError("El registro no está marcado pendiente_encontrar_pdf")
    stem=f"decreto-{number:03d}-{year}"; pdf_root=repo/f"archivos/decretos/{year}"; md_root=repo/f"docs/decretos/{year}"; data_root=repo/f"datos/decretos/{year}"
    expected_pdf=_safe_repo_path(repo,f"archivos/decretos/{year}/{stem}.pdf",allowed_root=pdf_root)
    if expected_pdf.exists():
        raise ValueError(f"Existe un PDF local para {stem}; debe revisarse y retirarse explícitamente antes de marcarlo pendiente")
    md_path=_safe_repo_path(repo,f"docs/decretos/{year}/{stem}.md",allowed_root=md_root); json_path=_safe_repo_path(repo,f"datos/decretos/{year}/{stem}.json",allowed_root=data_root)
    source_url=_markdown_url(record.get("url_fuente_oficial")); open_url=_markdown_url(record.get("url_documento_consultoria_abrir")); download_url=_markdown_url(record.get("url_documento_consultoria_descargar"))
    alerts=record.get("alertas_revision")
    if not isinstance(alerts,list) or not alerts or any(not str(item).strip() for item in alerts):
        raise ValueError("Un pendiente_encontrar_pdf requiere alertas_revision")
    fragment_ids=", ".join(_cell(item) for item in evidence["document_ids_recortes"])
    markdown="\n".join([
        f"# Decreto núm. {number:03d}-{year}","",'!!! warning "Aviso"',"    LEY.DO no es una fuente oficial. Verifique este documento contra la fuente oficial indicada.","    LEY.DO no ofrece asesoría legal.","","## Metadata","",f"- Tipo de documento: decreto",f"- Número: {number:03d}",f"- Año: {year}",f"- Título en la fuente: {_cell(record.get('titulo'))}",f"- Fecha: {_cell(record.get('fecha_documento'))}",f"- Gaceta Oficial: {_cell(record.get('gaceta_oficial'))}",f"- Institución fuente: {_cell(record.get('institucion_fuente'))}",f"- Fuente oficial: [{_cell(source_url)}]({source_url})",f"- Registro oficial: [Abrir en Consultoría Jurídica]({open_url})",f"- Endpoint de descarga registrado: [{_cell(download_url)}]({download_url})",f"- PDF original completo: pendiente de localizar",f"- Estado de extracción: `pendiente_encontrar_pdf`",f"- Estado de revisión: `pendiente_revision`","","## Texto","","El texto no se incorpora porque no se recuperó un PDF oficial completo y verificable desde el registro correspondiente.","","## Notas de revisión","",f"- {_cell(evidence.get('motivo'))}",f"- IDs oficiales de recortes observados: {fragment_ids}.","- Los recortes no se fusionaron ni se presentaron como PDF original.",*[f"- {_cell(alert)}" for alert in alerts],"- Pendiente localizar un PDF oficial completo.","- Pendiente de revisión humana.",""])
    _atomic_write_text(md_path,markdown)
    metadata={
        "tipo_documento":"decreto","categoria_inventario_fuente":"decretos","numero":f"{number:03d}","numero_registro_fuente":str(record.get("numero") or ""),"anio":str(year),"titulo":str(record.get("titulo") or ""),"fecha":str(record.get("fecha_documento") or ""),"gaceta_oficial":str(record.get("gaceta_oficial") or ""),"institucion_fuente":str(record.get("institucion_fuente") or ""),"url_fuente_oficial":str(record.get("url_fuente_oficial") or ""),"url_pdf_original":str(record.get("url_documento_consultoria_descargar") or ""),"url_documento_oficial":str(record.get("url_documento_consultoria_abrir") or ""),"document_id_consultoria":str(record.get("document_id_consultoria") or ""),"fecha_consulta":datetime.now(timezone.utc).date().isoformat(),"ruta_pdf_local":"","ruta_markdown":md_path.relative_to(repo).as_posix(),"ruta_json":json_path.relative_to(repo).as_posix(),"sha256_pdf_original":"","sha256_markdown":_hash_file(md_path),"estado_revision":"pendiente_revision","estado_publicacion":"descubierto","estado_extraccion":"pendiente_encontrar_pdf","commit_publicacion":"","evidencia_pdf_no_disponible":evidence,"alertas_revision":alerts,"notas":"No se recuperó un PDF oficial completo. Los recortes oficiales no se fusionaron. Pendiente localizar PDF y revisar humanamente."
    }
    _atomic_write_text(json_path,json.dumps(metadata,ensure_ascii=False,indent=2)+"\n")


def process_documents(repo,inventario_path,year,numbers,downloader=download_pdf,normalizer=None):
    repo=Path(repo).resolve(); inventory_resolved=Path(inventario_path).resolve()
    try: inventory_relative=inventory_resolved.relative_to(repo)
    except ValueError as exc: raise ValueError(f"Inventario fuera del repositorio: {inventario_path}") from exc
    inventario_path=_safe_repo_path(repo,inventory_relative,allowed_root=repo)
    records=json.loads(inventario_path.read_text(encoding="utf-8"))["documentos"]["decretos"]
    by_number={}; ids=set()
    for record in records:
        document_id=str(record.get("document_id_consultoria") or "").strip()
        if not document_id: raise ValueError("ID de documento ausente en el inventario reconciliado")
        if document_id in ids: raise ValueError(f"ID de documento duplicado en el inventario reconciliado: {document_id}")
        ids.add(document_id); number=_numero(record)
        if number is not None and _anio(record)==year: by_number.setdefault(number,[]).append(record)
    if normalizer is None:
        try: from scripts.normalizar_decretos_consultoria import run as normalizer
        except ModuleNotFoundError: from normalizar_decretos_consultoria import run as normalizer
    result={"ok":[],"errors":[]}
    pdf_root=repo/f"archivos/decretos/{year}"; data_root=repo/f"datos/decretos/{year}"
    for number in numbers:
        try:
            candidates=by_number.get(number,[])
            if len(candidates)!=1:
                raise ValueError(f"Se esperaban 1 registro para {number}; encontrados: {len(candidates)}")
            record=candidates[0]; stem=f"decreto-{number:03d}-{year}"
            if record.get("estado_extraccion") == "pendiente_encontrar_pdf":
                _write_pending_package(repo,year,number,record)
                result["ok"].append(number)
                continue
            canonical=_safe_repo_path(repo,f"archivos/decretos/{year}/{stem}.pdf",allowed_root=pdf_root)
            canonical_url=_validate_official_url(record["url_documento_consultoria_descargar"])
            rendition_pairs=[]
            for rendition in record.get("rendiciones_oficiales_relacionadas",[]):
                path=_safe_repo_path(repo,rendition["ruta_pdf_local"],allowed_root=pdf_root)
                _validate_official_url(rendition["url_pdf_oficial"]); rendition_pairs.append((rendition,path))
            expected=str(record.get("sha256_pdf") or "").strip().lower()
            if not expected:
                for rendition,path in rendition_pairs:
                    candidate=str(rendition.get("sha256_pdf") or "").strip().lower()
                    if path==canonical and candidate: expected=candidate; break
            package=_safe_repo_path(repo,f"datos/decretos/{year}/{stem}.json",allowed_root=data_root)
            if not expected and package.is_file():
                try: previous=json.loads(package.read_text(encoding="utf-8"))
                except (OSError,json.JSONDecodeError): previous={}
                if str(previous.get("document_id_consultoria") or "")==str(record.get("document_id_consultoria") or "") and _numero(previous)==number and _anio(previous)==year:
                    candidate=str(previous.get("sha256_pdf_original") or "").strip().lower()
                    if re.fullmatch(r"[0-9a-f]{64}",candidate): expected=candidate
            canonical_digest=_hash_file(canonical) if _valid_pdf(canonical) else ""
            if not canonical_digest or (expected and canonical_digest.lower()!=expected):
                kwargs={"expected_hash":expected} if expected else {}
                canonical_digest=downloader(canonical_url,canonical,**kwargs)
            if expected and canonical_digest.lower()!=expected:
                raise ValueError(f"Hash inesperado para el PDF canónico {canonical}")
            for rendition,path in rendition_pairs:
                rendition_expected=str(rendition.get("sha256_pdf","")).lower()
                digest=_hash_file(path) if _valid_pdf(path) else ""
                if not digest or (rendition_expected and digest.lower()!=rendition_expected):
                    kwargs={"expected_hash":rendition_expected} if rendition_expected else {}
                    digest=downloader(rendition["url_pdf_oficial"],path,**kwargs)
                if rendition_expected and digest.lower()!=rendition_expected:
                    raise ValueError(f"Hash inesperado para la rendición {path}")
            normalizer(repo,year,[number],documentos_explicitos={number:record["document_id_consultoria"]},inventario_path=inventario_path)
            result["ok"].append(number)
        except Exception as exc:
            result["errors"].append({"numero":number,"error":str(exc)})
    return result

def _atomic_write_text(destination,content):
    destination=Path(destination); destination.parent.mkdir(parents=True,exist_ok=True); temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",newline="\n",delete=False,dir=destination.parent,prefix=destination.name+".",suffix=".tmp") as handle:
            temporary=Path(handle.name); handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary,destination); temporary=None
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def _cell(value):
    sanitized=html.escape(str(value or "").replace("\r"," ").replace("\n"," ").strip(),quote=True)
    for char,entity in (("|","&#124;"),("`","&#96;"),("[","&#91;"),("]","&#93;"),("(","&#40;"),(")","&#41;")):
        sanitized=sanitized.replace(char,entity)
    return sanitized


def _renditions_are_valid(repo,expected_items,actual_items,year):
    if len(expected_items)!=len(actual_items): return False
    actual_by_id={}
    for item in actual_items:
        document_id=str(item.get("document_id_consultoria") or "").strip()
        if not document_id or document_id in actual_by_id: return False
        actual_by_id[document_id]=item
    for expected in expected_items:
        document_id=str(expected.get("document_id_consultoria") or "").strip(); actual=actual_by_id.get(document_id)
        if actual is None: return False
        expected_hash=str(expected.get("sha256_pdf") or "").lower()
        if not expected_hash or str(actual.get("sha256_pdf") or "").lower()!=expected_hash: return False
        if str(actual.get("rol_archivistico") or "")!=str(expected.get("rol_archivistico") or ""): return False
        try:
            pdf_root=Path(repo).resolve()/f"archivos/decretos/{year}"
            expected_path=_safe_repo_path(repo,expected.get("ruta_pdf_local",""),allowed_root=pdf_root); actual_path=_safe_repo_path(repo,actual.get("ruta_pdf_local",""),allowed_root=pdf_root)
            _validate_official_url(expected.get("url_pdf_oficial","")); _validate_official_url(actual.get("url_pdf_oficial",""))
        except (ValueError,TypeError): return False
        if expected_path!=actual_path or not _valid_pdf(actual_path) or _hash_file(actual_path)!=expected_hash: return False
        if _markdown_url(expected.get("url_pdf_oficial",""))!=_markdown_url(actual.get("url_pdf_oficial","")): return False
    return True


def _validated_packages(repo,inventory,year):
    repo=Path(repo).resolve(); canonical_by_identity={}; document_ids=set(); source_ids=set()
    for source in inventory.get("registros_fuente",[]):
        source_id=str(source.get("document_id_consultoria") or "").strip()
        if not source_id: raise ValueError("ID de registro fuente ausente")
        if source_id in source_ids: raise ValueError(f"ID de registro fuente duplicado: {source_id}")
        source_ids.add(source_id)
    for record in inventory.get("documentos",{}).get("decretos",[]):
        identity=record.get("identidad_documental_numero"); number=_numero(record)
        if not isinstance(identity,int): identity=number
        if identity is None or _anio(record)!=year: continue
        if number!=identity: raise ValueError(f"Identidad documental incoherente: identidad {identity}, número {record.get('numero','')}")
        document_id=str(record.get("document_id_consultoria") or "").strip()
        if not document_id: raise ValueError(f"ID de documento ausente para la identidad {identity}")
        if document_id in document_ids: raise ValueError(f"ID de documento duplicado en el inventario reconciliado: {document_id}")
        document_ids.add(document_id)
        if identity in canonical_by_identity: raise ValueError(f"Identidad documental duplicada para el índice: {identity}")
        canonical_by_identity[identity]=record
    validated={}
    for identity,record in canonical_by_identity.items():
        stem=f"decreto-{identity:03d}-{year}"; pdf_root=repo/f"archivos/decretos/{year}"; md_root=repo/f"docs/decretos/{year}"; data_root=repo/f"datos/decretos/{year}"
        try:
            package=_safe_repo_path(repo,f"datos/decretos/{year}/{stem}.json",allowed_root=data_root)
            expected_pdf=_safe_repo_path(repo,f"archivos/decretos/{year}/{stem}.pdf",allowed_root=pdf_root)
            expected_md=_safe_repo_path(repo,f"docs/decretos/{year}/{stem}.md",allowed_root=md_root)
        except ValueError: continue
        try: metadata=json.loads(package.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError): continue
        expected_id=str(record.get("document_id_consultoria") or "").strip()
        if not expected_id or str(metadata.get("document_id_consultoria") or "").strip()!=expected_id: continue
        if _numero(metadata)!=identity or _anio(metadata)!=year: continue
        try:
            md_path=_safe_repo_path(repo,metadata.get("ruta_markdown",""),allowed_root=md_root)
            json_path=_safe_repo_path(repo,metadata.get("ruta_json",""),allowed_root=data_root)
        except ValueError: continue
        if md_path!=expected_md or json_path!=package or not md_path.is_file(): continue
        if not metadata.get("sha256_markdown") or _hash_file(md_path)!=str(metadata.get("sha256_markdown")).lower(): continue
        pending=record.get("estado_extraccion")=="pendiente_encontrar_pdf"
        if pending:
            try: evidence=_pending_evidence(record)
            except ValueError: continue
            if metadata.get("estado_revision")!="pendiente_revision" or metadata.get("estado_publicacion")!="descubierto" or metadata.get("estado_extraccion")!="pendiente_encontrar_pdf": continue
            if metadata.get("ruta_pdf_local")!="" or metadata.get("sha256_pdf_original")!="" or expected_pdf.exists(): continue
            if metadata.get("evidencia_pdf_no_disponible")!=evidence or metadata.get("rendiciones_oficiales_relacionadas"): continue
        else:
            try: pdf_path=_safe_repo_path(repo,metadata.get("ruta_pdf_local",""),allowed_root=pdf_root)
            except ValueError: continue
            if pdf_path!=expected_pdf or not _valid_pdf(pdf_path): continue
            if not metadata.get("sha256_pdf_original") or _hash_file(pdf_path)!=str(metadata.get("sha256_pdf_original")).lower(): continue
            if metadata.get("estado_revision")!="pendiente_revision" or metadata.get("estado_publicacion")!="normalizado" or metadata.get("estado_extraccion")!="extraido_desde_pdf_oficial": continue
        expected_urls={"url_fuente_oficial":record.get("url_fuente_oficial"),"url_pdf_original":record.get("url_documento_consultoria_descargar"),"url_documento_oficial":record.get("url_documento_consultoria_abrir")}
        urls_valid=True
        for field,expected_url in expected_urls.items():
            actual_url=metadata.get(field)
            try: expected_normalized=_markdown_url(expected_url); actual_normalized=_markdown_url(actual_url)
            except (ValueError,TypeError): urls_valid=False; break
            if expected_normalized!=actual_normalized: urls_valid=False; break
        if not urls_valid: continue
        expected_institution=str(record.get("institucion_fuente") or "").strip()
        if not expected_institution or str(metadata.get("institucion_fuente") or "").strip()!=expected_institution: continue
        try: markdown_content=md_path.read_text(encoding="utf-8")
        except OSError: continue
        required=("LEY.DO no es una fuente oficial.","LEY.DO no ofrece asesoría legal.","## Metadata","## Texto","## Notas de revisión")
        if any(marker not in markdown_content for marker in required): continue
        if pending:
            validated[identity]=metadata
            continue
        expected_hash=str(record.get("sha256_pdf") or "").strip().lower()
        if not expected_hash:
            for rendition in record.get("rendiciones_oficiales_relacionadas",[]):
                try: rendition_path=_safe_repo_path(repo,rendition.get("ruta_pdf_local",""),allowed_root=pdf_root)
                except ValueError: continue
                if rendition_path==expected_pdf:
                    expected_hash=str(rendition.get("sha256_pdf") or "").strip().lower(); break
        if expected_hash and str(metadata.get("sha256_pdf_original") or "").lower()!=expected_hash: continue
        if not _renditions_are_valid(repo,record.get("rendiciones_oficiales_relacionadas",[]),metadata.get("rendiciones_oficiales_relacionadas",[]),year): continue
        validated[identity]=metadata
    return validated


def generate_index(repo,inventario_path,year):
    repo=Path(repo).resolve(); inventory_resolved=Path(inventario_path).resolve()
    try: inventory_relative=inventory_resolved.relative_to(repo)
    except ValueError as exc: raise ValueError(f"Inventario fuera del repositorio: {inventario_path}") from exc
    inventario_path=_safe_repo_path(repo,inventory_relative,allowed_root=repo); inventory=json.loads(inventario_path.read_text(encoding="utf-8"))
    pdf_root=repo/f"archivos/decretos/{year}"; md_root=repo/f"docs/decretos/{year}"; data_root=repo/f"datos/decretos/{year}"
    _safe_repo_path(repo,f"archivos/decretos/{year}",allowed_root=pdf_root); _safe_repo_path(repo,f"docs/decretos/{year}",allowed_root=md_root); _safe_repo_path(repo,f"datos/decretos/{year}",allowed_root=data_root)
    records=inventory.get("registros_fuente",[]); summary=inventory.get("resumen",{})
    source_ids=set()
    for record in records:
        document_id=str(record.get("document_id_consultoria") or "").strip()
        if not document_id: raise ValueError("ID de registro fuente ausente")
        if document_id in source_ids: raise ValueError(f"ID de registro fuente duplicado: {document_id}")
        source_ids.add(document_id)
    canonical_records=[record for record in inventory.get("documentos",{}).get("decretos",[]) if _anio(record)==year]
    expected={record.get("identidad_documental_numero") if isinstance(record.get("identidad_documental_numero"),int) else _numero(record) for record in canonical_records}
    declared_rendition_paths=set()
    for record in canonical_records:
        for rendition in record.get("rendiciones_oficiales_relacionadas",[]):
            path=_safe_repo_path(repo,rendition.get("ruta_pdf_local",""),allowed_root=pdf_root).relative_to(repo).as_posix(); declared_rendition_paths.add(path); _validate_official_url(rendition.get("url_pdf_oficial",""))
    actual_rendition_paths={path.relative_to(repo).as_posix() for path in pdf_root.glob(f"decreto-*-{year}-*.pdf")} if pdf_root.exists() else set()
    expected_rendition_paths={path for path in declared_rendition_paths if re.fullmatch(rf"archivos/decretos/{year}/decreto-\d+-{year}\.pdf",path) is None}
    if actual_rendition_paths!=expected_rendition_paths:
        raise ValueError(f"Rendiciones oficiales faltantes o huérfanas: faltan={sorted(expected_rendition_paths-actual_rendition_paths)}, sobran={sorted(actual_rendition_paths-expected_rendition_paths)}")
    actual={"json":set(),"markdown":set(),"pdf":set()}
    for kind,directory,extension in (("json",data_root,"json"),("markdown",md_root,"md"),("pdf",pdf_root,"pdf")):
        if directory.exists():
            for path in directory.glob(f"decreto-*-{year}.{extension}"):
                match=re.fullmatch(rf"decreto-(\d+)-{year}\.{extension}",path.name)
                if match: actual[kind].add(int(match.group(1)))
    orphans={kind:sorted(numbers-expected) for kind,numbers in actual.items() if numbers-expected}
    if orphans: raise ValueError(f"Paquetes canónicos huérfanos respecto del inventario reconciliado: {orphans}")
    packages=_validated_packages(repo,inventory,year)
    lines=[f"# Decretos de {year}","","!!! warning \"Aviso\"","    LEY.DO no es una fuente oficial. Verifique cada documento contra la fuente oficial indicada.","    LEY.DO no ofrece asesoría legal.","","## Cobertura","",f"- Registros preservados del inventario oficial reconciliado: {summary.get('registros_fuente',len(records))}.",f"- Identidades documentales normalizadas: {len(packages)} de {summary.get('identidades_documentales','')}.","- Estado editorial: pendiente de revisión humana.","","Los registros repetidos, atípicos o contextuales se conservan como filas independientes para mantener su trazabilidad. La ausencia de un número en este inventario no determina su inexistencia jurídica.","","## Inventario oficial reconciliado","","| Número en fuente | Documento relacionado | Título en fuente | Fecha | Gaceta | Registro oficial | Estado |","|---|---|---|---|---|---|---|"]
    for record in records:
        identity=record.get("identidad_documental_numero"); metadata=packages.get(identity) if isinstance(identity,int) else None; related=""
        if metadata is not None: related=f"[Decreto {identity:03d}-{year}](decreto-{identity:03d}-{year}.md)"
        role=record.get("rol_reconciliacion","")
        if role=="rendicion_complementaria": state="rendición oficial relacionada · pendiente_revision"
        elif role.startswith("fuente_contextual"): state="fuente contextual oficial · pendiente_revision"
        elif metadata is not None and metadata.get("estado_extraccion")=="pendiente_encontrar_pdf": state="pendiente_encontrar_pdf · pendiente_revision"
        elif metadata is not None: state="normalizado con alerta · pendiente_revision" if metadata.get("alertas_revision") else "normalizado · pendiente_revision"
        else: state="descubierto · pendiente_revision"
        document_id=_cell(record.get("document_id_consultoria")); official=str(record.get("url_documento_consultoria_abrir") or "").strip()
        if official: source=f"[ID {document_id}]({_markdown_url(official)})"
        else: source=f"ID {document_id}"
        lines.append("| "+" | ".join([f"`{_cell(record.get('numero'))}`",related,_cell(record.get("titulo")),_cell(record.get("fecha_documento")),_cell(record.get("gaceta_oficial")),source,state])+" |")
    destination=_safe_repo_path(repo,f"docs/decretos/{year}/index.md",allowed_root=md_root); _atomic_write_text(destination,"\n".join(lines)+"\n")
    return destination


def main(argv=None,processor=process_documents):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo",required=True,type=Path)
    parser.add_argument("--inventario",required=True,type=Path)
    parser.add_argument("--anio",required=True,type=int)
    parser.add_argument("--numeros",required=True)
    parser.add_argument("--manifiesto",required=True,type=Path)
    parser.add_argument("--reprocess",action="store_true",help="Reprocesa todas las identidades solicitadas aunque el manifiesto las marque ok")
    args=parser.parse_args(argv); numbers=parse_numbers(args.numeros); repo=args.repo.resolve()
    try:
        inventory_relative=args.inventario.resolve().relative_to(repo); manifest_relative=args.manifiesto.resolve().relative_to(repo)
        inventory_path=_safe_repo_path(repo,inventory_relative,allowed_root=repo); manifest_path=_safe_repo_path(repo,manifest_relative,allowed_root=repo)
    except ValueError:
        return 1
    inventory_hash=_hash_file(inventory_path); inventory_display=inventory_relative.as_posix()
    try: inventory_data=json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError): return 1
    canonical_requested=set(); has_reconciled_scope="documentos" in inventory_data
    for record in inventory_data.get("documentos",{}).get("decretos",[]):
        identity=record.get("identidad_documental_numero"); identity=identity if isinstance(identity,int) else _numero(record)
        if identity in numbers and _anio(record)==args.anio: canonical_requested.add(identity)
    if has_reconciled_scope and canonical_requested!=set(numbers):
        return 1
    validated_before=set(_validated_packages(repo,inventory_data,args.anio)) if canonical_requested else set(); completed=[]
    if manifest_path.is_file():
        original=manifest_path.read_text(encoding="utf-8")
        try: previous=json.loads(original)
        except (OSError,json.JSONDecodeError): return 1
        result_previous=previous.get("resultado")
        compatible=(
            previous.get("schema_version")=="1.1"
            and previous.get("anio")==args.anio
            and previous.get("inventario")==inventory_display
            and previous.get("sha256_inventario")==inventory_hash
            and previous.get("numeros")==numbers
            and isinstance(result_previous,dict)
            and isinstance(result_previous.get("ok"),list)
            and isinstance(result_previous.get("errors"),list)
            and all(isinstance(item,int) and item in numbers for item in result_previous.get("ok",[]))
        )
        if not compatible: return 1
        if not args.reprocess:
            completed=[number for number in result_previous.get("ok",[]) if not canonical_requested or number in validated_before]
    result={"ok":sorted(set(completed)),"errors":[]}
    def persist(state):
        payload={"schema_version":"1.1","fecha_ejecucion":datetime.now(timezone.utc).isoformat(),"anio":args.anio,"inventario":inventory_display,"sha256_inventario":inventory_hash,"numeros":numbers,"estado":state,"resultado":result}
        _atomic_write_text(manifest_path,json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    persist("en_progreso")
    for number in numbers:
        if number in result["ok"]: continue
        try: partial=processor(repo,inventory_path,args.anio,[number])
        except Exception as exc: partial={"ok":[],"errors":[{"numero":number,"error":str(exc)}]}
        result["ok"]=sorted(set(result["ok"]+partial.get("ok",[]))); result["errors"].extend(partial.get("errors",[])); persist("en_progreso_con_errores" if result["errors"] else "en_progreso")
    if result["errors"]:
        persist("completado_con_errores"); return 1
    if canonical_requested:
        missing=sorted(canonical_requested-set(_validated_packages(repo,inventory_data,args.anio)))
        if missing:
            result["errors"].append({"numero":None,"error":f"Paquetes ausentes, obsoletos o inconsistentes: {missing}"}); persist("error"); return 1
    try: generate_index(repo,inventory_path,args.anio)
    except Exception as exc:
        result["errors"].append({"numero":None,"error":f"Índice no generado: {exc}"}); persist("error"); return 1
    persist("completado"); return 0


if __name__=="__main__":
    raise SystemExit(main())
