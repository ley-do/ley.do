#!/usr/bin/env python3
"""Normaliza PDFs oficiales de decretos de Consultoría Jurídica para LEY.DO."""
import argparse, hashlib, html, json, re
from datetime import date
from pathlib import Path
import pymupdf

def sha(p):
    digest=hashlib.sha256()
    with Path(p).open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""): digest.update(chunk)
    return digest.hexdigest()


def md_text(value,multiline=False):
    text=str(value or "").replace("\r","")
    if not multiline: text=" ".join(text.splitlines()).strip()
    text=html.escape(text,quote=True)
    for char,entity in (("`","&#96;"),("[","&#91;"),("]","&#93;"),("|","&#124;")):
        text=text.replace(char,entity)
    if multiline: text=re.sub(r"(?m)^([#>*+-])",r"\\\1",text)
    return text


def official_link(url):
    try: from scripts.procesar_decretos_consultoria import _markdown_url
    except ModuleNotFoundError: from procesar_decretos_consultoria import _markdown_url
    url=str(url or "").strip()
    if not url: return "no disponible"
    return f"[{md_text(url)}]({_markdown_url(url)})"


def nint(v):
    m=re.match(r"\s*0*(\d+)\s*-",v or "")
    return int(m.group(1)) if m else None

MESES={"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,"julio":7,"agosto":8,"septiembre":9,"setiembre":9,"octubre":10,"noviembre":11,"diciembre":12}

def fecha_dado(pages,year):
    del year  # Compatibilidad de API; el año debe provenir del PDF observable.
    text="\n".join(pages); markers=list(re.finditer(r"\bDAD[OA]\b",text,re.I))
    if not markers: return ""
    snippet=text[markers[-1].start():markers[-1].start()+900]
    month=re.search(r"\b("+"|".join(MESES)+r")\b",snippet,re.I)
    if not month: return ""
    days=[int(x) for x in re.findall(r"\(\s*(\d{1,2})(?:\s*\)|(?:er\.)?\s*\))",snippet[:month.start()],re.I)]
    years=[int(x) for x in re.findall(r"(?:\(\s*)?(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)(?:\s*\))?",snippet[month.end():])]
    if not days or not years: return ""
    day=days[-1]; month_number=MESES[month.group(1).lower()]; observed_year=years[0]
    try: date(observed_year,month_number,day)
    except ValueError: return ""
    return f"{day:02d}/{month_number:02d}/{observed_year}"

def reflow(text):
    lines=[re.sub(r"\s+"," ",x).strip() for x in text.replace("\r","").split("\n")]
    marker=re.compile(r"^(?:(?:Dec\.|Regl\.)\s*(?:(?:núm\.|No\.)\s*)?|LUIS ABINADER|Presidente de la República|N[ÚU]MERO:|CONSIDERANDO|VIST[OA]|DECRETO:|ART[IÍ]CULO|PÁRRAFO|DADO)",re.I)
    blocks=[]; current=[]
    for line in lines:
        if re.fullmatch(r"-\s*\d+\s*-",line): continue
        if not line:
            if current: blocks.append(" ".join(current)); current=[]
        elif marker.match(line) and current:
            blocks.append(" ".join(current)); current=[line]
        else: current.append(line)
    if current: blocks.append(" ".join(current))
    return "\n\n".join(blocks).strip()

def extract(pdf,n,yy):
    doc=pymupdf.open(pdf); texts=[p.get_text("text") for p in doc]; doc.close()
    full_year=f"20{yy}" if len(yy)==2 else yy; year_token=rf"(?:{re.escape(yy)}|{re.escape(full_year)})"
    start=re.compile(rf"(?im)^(?P<clase>Dec\.|Regl\.)\s*(?:(?:núm\.|No\.)\s*)?(?P<numero>0*{n}\s*-\s*{year_token})\b",re.I)
    truncated=re.compile(rf"(?im)^(?P<clase>ec\.)\s*(?:núm\.|No\.)\s*(?P<numero>0*{n}\s*-\s*{year_token})\b",re.I)
    formal=re.compile(rf"(?im)^N[ÚU]MERO:\s*(?P<numero>0*{n}\s*-\s*{year_token})\b",re.I)
    formal_any=re.compile(r"(?im)^N[ÚU]MERO:\s*(?P<numero>\d+\s*-\s*(?P<anio>\d{2}|\d{4}))\b",re.I)
    summary_neighbor=re.compile(r"(?im)^(?:Dec\.|Regl\.|ec\.)\s*(?:(?:núm\.|No\.)\s*)?(?P<numero>\d+)\s*-\s*(?P<anio>\d{2}|\d{4})\b",re.I)
    formal_neighbor=re.compile(r"(?im)^N[ÚU]MERO:\s*(?P<numero>\d+)\s*-\s*(?P<anio>\d{2}|\d{4})\b",re.I)
    all_formals=[(page_index,match) for page_index,text in enumerate(texts) for match in formal_any.finditer(text)]
    sole_formal=all_formals[0] if len(all_formals)==1 else None
    begun=False; trimmed=[]; pages=[]; clase_encabezado=""; numero_encabezado=""; closure_seen=False
    for page_index,text in enumerate(texts):
        if not begun:
            m=start.search(text) or truncated.search(text); formal_only=False
            if not m:
                m=formal.search(text); formal_only=bool(m)
            if not m and sole_formal and sole_formal[0]==page_index:
                m=sole_formal[1]; formal_only=True
            if not m: continue
            if text[:m.start()].strip(): trimmed.append("fragmento_anterior")
            clase_encabezado="Dec." if formal_only else m.group("clase"); numero_encabezado=re.sub(r"\s+","",m.group("numero")); text=text[m.start():]; begun=True
        candidates=sorted([*summary_neighbor.finditer(text),*formal_neighbor.finditer(text)],key=lambda item:item.start())
        end=None; numero_vecino=None
        for candidate in candidates:
            candidate_number=int(candidate.group("numero")); candidate_year=candidate.group("anio")
            same_target_year=candidate_year in {yy,full_year}
            if candidate_number==n and same_target_year:
                continue
            closure_before=closure_seen or bool(re.search(r"\bDAD[OA]\b",text[:candidate.start()],re.I))
            if closure_before or (same_target_year and candidate_number>n):
                end=candidate; numero_vecino=candidate_number; break
        if end:
            text=text[:end.start()]
            if numero_vecino not in trimmed: trimmed.append(numero_vecino)
        if re.search(r"\bDAD[OA]\b",text,re.I): closure_seen=True
        text=reflow(text)
        if text: pages.append(text)
        if end: break
    return pages,trimmed,("extraido_desde_pdf_oficial" if begun else "encabezado_no_encontrado"),clase_encabezado,numero_encabezado

def title(pages,n,yy,year):
    if not pages: return f"Decreto núm. {n:03d}-{year}"
    text=pages[0].split("\n\n",1)[0]
    if re.match(r"^N[ÚU]MERO:",text,re.I): return f"Decreto núm. {n:03d}-{year}"
    text=re.sub(rf"^(?:Dec\.|Regl\.|ec\.)\s*(?:(?:núm\.|No\.)\s*)?0*{n}\s*-\s*\d{{2,4}}\s*","",text,flags=re.I)
    text=re.sub(r"\s*G\.\s*O\.\s*núm\..*$","",text,flags=re.I).strip().rstrip(".")
    return text or f"Decreto núm. {n:03d}-{year}"

def markdown(n,year,d,pages,hpdf,state,trimmed,clase_encabezado):
    t=title(pages,n,str(year)[-2:],year); es_reglamento=clase_encabezado.lower().startswith("regl") if clase_encabezado else False; tipo="reglamento" if es_reglamento else "decreto"; etiqueta="Reglamento" if es_reglamento else "Decreto"
    out=[f"# {etiqueta} núm. {n:03d}-{year}\n\n",'!!! warning "Aviso"\n    LEY.DO no es una fuente oficial. Verifique este documento contra la fuente oficial indicada.\n    LEY.DO no ofrece asesoría legal.\n\n',"## Metadata\n\n",f"- Tipo de documento: {tipo}\n- Número: {n:03d}\n- Año: {year}\n- Título detectado: {md_text(t)}\n- Fecha: {md_text(d.get('fecha_documento',''))}\n- Gaceta oficial: {md_text(d.get('gaceta_oficial',''))}\n- Institución fuente: {md_text(d.get('institucion_fuente',''))}\n",f"- Fuente oficial: {official_link(d.get('url_fuente_oficial',''))}\n- Documento oficial: {official_link(d.get('url_documento_consultoria_abrir',''))}\n- Descarga oficial: {official_link(d.get('url_documento_consultoria_descargar',''))}\n",f"- Hash SHA256 del PDF: `{hpdf}`\n- Estado de revisión: pendiente_revision\n\n## Texto\n\n"]
    if pages:
        for i,page in enumerate(pages,1): out += [f"### Página {i} del PDF\n\n",md_text(page,multiline=True),"\n\n"]
    else: out += ["Texto pendiente de extracción: encabezado esperado no localizado.\n\n"]
    out += ["## Notas de revisión\n\n- Pendiente de revisión humana.\n",f"- Estado de extracción: `{md_text(state)}`.\n","- Texto extraído automáticamente del PDF oficial y refluido para legibilidad; cotejar contra el PDF.\n"]
    if trimmed: out += ["- El PDF contenía fragmentos de decretos vecinos; se delimitaron usando sus encabezados oficiales.\n"]
    return "".join(out)


def run(repo,year,numbers,documentos_explicitos=None,inventario_path=None):
    try: from scripts.procesar_decretos_consultoria import _atomic_write_text, _safe_repo_path, _valid_pdf
    except ModuleNotFoundError: from procesar_decretos_consultoria import _atomic_write_text, _safe_repo_path, _valid_pdf
    repo=Path(repo).resolve(); inventario_path=inventario_path or repo/"fuentes"/f"consultoria_inventario_{year}_leyes_decretos.json"
    inventory_resolved=Path(inventario_path).resolve()
    try: inventory_relative=inventory_resolved.relative_to(repo)
    except ValueError as exc: raise ValueError(f"Inventario fuera del repositorio: {inventario_path}") from exc
    inventario_path=_safe_repo_path(repo,inventory_relative,allowed_root=repo)
    inv=json.loads(inventario_path.read_text(encoding="utf-8")); registros=inv["documentos"]["decretos"]
    docs={}
    for d in registros:
        numero=nint(d.get("numero",""))
        if numero is not None: docs.setdefault(numero,[]).append(d)
    docs_por_id={}
    for d in registros:
        document_id=str(d.get("document_id_consultoria") or "").strip()
        if not document_id:
            raise ValueError("ID de documento ausente en el inventario reconciliado")
        if document_id in docs_por_id:
            raise ValueError(f"ID de documento duplicado en el inventario reconciliado: {document_id}")
        docs_por_id[document_id]=d
    documentos_explicitos=documentos_explicitos or {}
    for n in numbers:
        document_id=documentos_explicitos.get(n)
        if document_id is not None and str(document_id) not in docs_por_id:
            raise KeyError(f"ID de documento no encontrado: {document_id}")
        if document_id is not None:
            d=docs_por_id[str(document_id)]
        else:
            candidatos=docs.get(n,[])
            if len(candidatos)!=1:
                raise ValueError(f"Se encontraron {len(candidatos)} múltiples registros para el número {n}; indique document_id_consultoria")
            d=candidatos[0]
        numero_fuente=str(d.get("numero") or "").strip()
        suffix=re.search(r"-\s*(\d{2}|\d{4})\s*$",numero_fuente)
        anio_fuente=str(d.get("anio") or "").strip()
        anio_coincide=bool(suffix and suffix.group(1) in {str(year),str(year)[-2:]}) if suffix else anio_fuente==str(year)
        if nint(numero_fuente)!=n or not anio_coincide:
            raise ValueError(f"El ID {d.get('document_id_consultoria','')} no corresponde al decreto {n}-{year}")
        stem=f"decreto-{n:03d}-{year}"; pdf_root=repo/"archivos"/"decretos"/str(year); md_root=repo/"docs"/"decretos"/str(year); data_root=repo/"datos"/"decretos"/str(year)
        pdf=_safe_repo_path(repo,f"archivos/decretos/{year}/{stem}.pdf",allowed_root=pdf_root)
        md=_safe_repo_path(repo,f"docs/decretos/{year}/{stem}.md",allowed_root=md_root)
        js=_safe_repo_path(repo,f"datos/decretos/{year}/{stem}.json",allowed_root=data_root)
        if not _valid_pdf(pdf): raise ValueError(f"PDF ausente o estructuralmente inválido: {pdf}")
        pages,trimmed,state,clase_encabezado,numero_encabezado=extract(pdf,n,str(year)[-2:]); hpdf=sha(pdf)
        rendiciones=[]
        for original in d.get("rendiciones_oficiales_relacionadas",[]):
            item=dict(original); ruta=_safe_repo_path(repo,item.get("ruta_pdf_local",""),allowed_root=pdf_root)
            if not _valid_pdf(ruta):
                raise ValueError(f"Rendición oficial ausente o estructuralmente inválida: {ruta}")
            calculado=sha(ruta); esperado_hash=item.get("sha256_pdf","")
            if esperado_hash and esperado_hash!=calculado:
                raise ValueError(f"Hash incorrecto para rendición oficial: {ruta}")
            item["sha256_pdf"]=calculado; rendiciones.append(item)
        joined_pages="\n".join(pages); formal=re.search(r"(?im)^N[ÚU]MERO:\s*(\d+)\s*-\s*(\d{2}|\d{4})\b",joined_pages)
        numero_formal=""; formal_number=None; formal_year=None
        if formal:
            formal_number=int(formal.group(1)); formal_year=formal.group(2); numero_formal=f"{formal_number}-{formal_year}"
            if formal_year not in {str(year),str(year)[-2:]}:
                raise ValueError(f"El año formal del PDF ({formal_year}) no corresponde a {year}")
        esperado=f"{n}-{str(year)[-2:]}"; summary_match=re.search(r"(\d+)\s*-\s*(\d{2}|\d{4})",numero_encabezado or "")
        discrepancia_encabezado=bool(summary_match and (int(summary_match.group(1))!=n or summary_match.group(2) not in {str(year),str(year)[-2:]}))
        discrepancia_formal=bool(formal_number is not None and formal_number!=n)
        discrepancia_numero=discrepancia_encabezado or discrepancia_formal; discrepancia_denominacion=clase_encabezado.lower()=="ec."; discrepancia=discrepancia_numero or discrepancia_denominacion
        fecha_fuente=d.get("fecha_documento",""); fecha_pdf=fecha_dado(pages,year); alertas=list(d.get("alertas_revision",[])); hay_dado=bool(re.search(r"\bDAD[OA]\b","\n".join(pages),re.I))
        estado_fecha_pdf="detectada" if fecha_pdf else ("clausula_dado_no_parseable" if hay_dado else "clausula_dado_no_detectada")
        if not fecha_pdf and not d.get("observacion_fecha_pdf"):
            alerta_fecha_incompleta="El PDF contiene una cláusula DADO, pero no fue posible extraer una fecha completa sin inferencia." if hay_dado else "No se detectó una cláusula DADO en el segmento extraído del PDF."
            if alerta_fecha_incompleta not in alertas: alertas.append(alerta_fecha_incompleta)
        markdown_text=markdown(n,year,d,pages,hpdf,state,trimmed,clase_encabezado)
        if alertas:
            bloque="".join(f"- {md_text(item)}\n" for item in alertas)
            markdown_text=markdown_text.replace("## Notas de revisión\n\n",f"## Notas de revisión\n\n{bloque}",1)
        if rendiciones:
            detalle=["- Rendiciones oficiales relacionadas:\n"]
            for item in rendiciones:
                detalle.append(f"  - ID `{md_text(item.get('document_id_consultoria',''))}`: {official_link(item.get('url_pdf_oficial',''))} — rol {md_text(item.get('rol_archivistico','rendición oficial'))}; SHA256 `{item.get('sha256_pdf','')}`.\n")
            markdown_text=markdown_text.replace("- Hash SHA256 del PDF:","".join(detalle)+"- Hash SHA256 del PDF:",1)
        if fecha_pdf and fecha_fuente and fecha_pdf!=fecha_fuente:
            alerta_fecha=f"La metadata oficial consultada indica {fecha_fuente}, mientras el apartado DADO del PDF indica {fecha_pdf}. Se conservan ambos valores para revisión humana."
            if alerta_fecha not in alertas: alertas.append(alerta_fecha)
            markdown_text=markdown_text.replace(f"- Fecha: {md_text(fecha_fuente)}\n",f"- Fecha: {md_text(fecha_fuente)}\n- Fecha observada en texto PDF: {md_text(fecha_pdf)}\n",1).replace("## Notas de revisión\n\n",f"## Notas de revisión\n\n- {md_text(alerta_fecha)}\n",1)
        if discrepancia:
            partes=[]; metadata_extra=""
            if discrepancia_numero:
                partes.append(f"El encabezado sumario del PDF indica `{numero_encabezado or 'no detectado'}`, mientras la línea formal indica `{numero_formal or 'no detectada'}` y la metadata oficial corresponde a `{esperado}`."); metadata_extra+=f"- Número en el encabezado sumario del PDF: `{numero_encabezado or 'no detectado'}`\n- Número formal en el PDF: `{numero_formal or 'no detectada'}`\n"
            if discrepancia_denominacion:
                partes.append(f"La denominación visible del encabezado está truncada como `{clase_encabezado} No.` en el PDF, mientras la línea formal identifica el documento como `{numero_formal or esperado}`."); metadata_extra+=f"- Denominación visible del encabezado del PDF: `{clase_encabezado} No.`\n"
            alerta=" ".join(partes)+" Se conserva la discrepancia para revisión humana."
            if alerta not in alertas: alertas.append(alerta)
            markdown_text=markdown_text.replace(f"- Número: {n:03d}\n",f"- Número: {n:03d}\n{metadata_extra}",1).replace("## Notas de revisión\n\n",f"## Notas de revisión\n\n- {alerta}\n",1)
        _atomic_write_text(md,markdown_text); hmd=sha(md); tipo_documento="reglamento" if clase_encabezado.lower().startswith("regl") else "decreto"
        meta={"tipo_documento":tipo_documento,"categoria_inventario_fuente":"decretos","denominacion_encabezado_pdf":clase_encabezado,"numero":f"{n:03d}","anio":str(year),"titulo":title(pages,n,str(year)[-2:],year),"fecha":fecha_fuente,"gaceta_oficial":d.get("gaceta_oficial",""),"institucion_fuente":d.get("institucion_fuente",""),"url_fuente_oficial":d.get("url_fuente_oficial",""),"url_pdf_original":d.get("url_documento_consultoria_descargar",""),"url_documento_oficial":d.get("url_documento_consultoria_abrir",""),"document_id_consultoria":d.get("document_id_consultoria",""),"fecha_consulta":d.get("fecha_consulta") or date.today().isoformat(),"ruta_pdf_local":f"archivos/decretos/{year}/{stem}.pdf","ruta_markdown":f"docs/decretos/{year}/{stem}.md","ruta_json":f"datos/decretos/{year}/{stem}.json","sha256_pdf_original":hpdf,"sha256_markdown":hmd,"estado_revision":"pendiente_revision","estado_publicacion":"normalizado","estado_extraccion":state,"fragmentos_decretos_vecinos_excluidos":trimmed,"commit_publicacion":"","notas":"Texto extraído automáticamente desde PDF oficial; verificar contra el PDF. Segmentación por encabezados cuando hubo documentos vecinos."}
        for campo in ("numero_registro_fuente","anio_metadata_fuente","inventario_origen","observacion_fecha_pdf"):
            if campo in d: meta[campo]=d[campo]
        if rendiciones: meta["rendiciones_oficiales_relacionadas"]=rendiciones
        meta.update({"estado_fecha_texto_pdf":estado_fecha_pdf,"fecha_texto_pdf_detectada":fecha_pdf})
        if fecha_pdf and fecha_fuente and fecha_pdf!=fecha_fuente:
            meta.update({"fecha_metadata_fuente":fecha_fuente})
        if numero_formal: meta["numero_formal_pdf"]=numero_formal
        if discrepancia:
            meta.update({"numero_encabezado_pdf":numero_encabezado})
        if alertas:
            meta.update({"alertas_revision":alertas,"notas":" ".join(alertas)+" Texto extraído automáticamente desde PDF oficial; verificar contra el PDF."})
        _atomic_write_text(js,json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
        print(f"OK {stem}: {len(pages)} página(s), PDF {hpdf[:12]}…, MD {hmd[:12]}…")
def main():
    p=argparse.ArgumentParser(); p.add_argument("--repo",type=Path,default=Path.cwd()); p.add_argument("--anio",type=int,required=True); p.add_argument("--numeros",required=True); p.add_argument("--documentos",default="",help="Mapeo numero=document_id_consultoria separado por comas"); a=p.parse_args()
    documentos={}
    for item in a.documentos.split(","):
        if item.strip():
            numero,document_id=item.split("=",1); documentos[int(numero)]=document_id.strip()
    run(a.repo.resolve(),a.anio,[int(x) for x in a.numeros.split(",")],documentos)
if __name__=="__main__": main()
