#!/usr/bin/env python3
"""Normaliza PDFs oficiales de decretos de Consultoría Jurídica para LEY.DO."""
import argparse, hashlib, json, re
from datetime import date
from pathlib import Path
import pymupdf

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def nint(v):
    m=re.match(r"\s*0*(\d+)\s*-",v or "")
    return int(m.group(1)) if m else None

MESES={"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,"julio":7,"agosto":8,"septiembre":9,"setiembre":9,"octubre":10,"noviembre":11,"diciembre":12}

def fecha_dado(pages,year):
    text="\n".join(pages); pos=max(text.lower().rfind("dado"),text.lower().rfind("dada"))
    if pos<0: return ""
    snippet=text[pos:pos+900]; month=re.search(r"\b("+"|".join(MESES)+r")\b",snippet,re.I)
    if not month: return ""
    days=[int(x) for x in re.findall(r"\(\s*(\d{1,2})",snippet[:month.start()]) if 1<=int(x)<=31]
    return f"{days[-1]:02d}/{MESES[month.group(1).lower()]:02d}/{year}" if days else ""

def reflow(text):
    lines=[re.sub(r"\s+"," ",x).strip() for x in text.replace("\r","").split("\n")]
    marker=re.compile(r"^(?:(?:Dec\.|Regl\.)\s*(?:(?:núm\.|No\.)\s*)?|LUIS ABINADER|Presidente de la República|NÚMERO:|CONSIDERANDO|VIST[OA]|DECRETO:|ART[IÍ]CULO|PÁRRAFO|DADO)",re.I)
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
    start=re.compile(rf"(?im)^(?P<clase>Dec\.|Regl\.)\s*(?:(?:núm\.|No\.)\s*)?(?P<numero>0*{n}\s*-\s*{yy})\b",re.I)
    alternate=re.compile(rf"(?im)^(?P<clase>Dec\.|Regl\.)\s*(?:(?:núm\.|No\.)\s*)?(?P<numero>0*{n}\s*-\s*\d{{2,4}})\b",re.I)
    truncated=re.compile(rf"(?im)^(?P<clase>ec\.)\s*(?:núm\.|No\.)\s*(?P<numero>0*{n}\s*-\s*\d{{2,4}})\b",re.I)
    formal=re.compile(rf"(?im)^N[ÚU]MERO:\s*(?P<numero>0*{n}\s*-\s*\d{{2,4}})\b",re.I)
    neighbor=re.compile(rf"(?im)^(?:Dec\.|Regl\.)\s*(?:(?:núm\.|No\.)\s*)?(\d+)\s*-\s*{yy}\b",re.I)
    begun=False; trimmed=[]; pages=[]; clase_encabezado=""; numero_encabezado=""
    for text in texts:
        if not begun:
            m=start.search(text) or alternate.search(text) or truncated.search(text); formal_only=False
            if not m:
                m=formal.search(text); formal_only=bool(m)
            if not m: continue
            if text[:m.start()].strip(): trimmed.append("fragmento_anterior")
            clase_encabezado="Dec." if formal_only else m.group("clase"); numero_encabezado=re.sub(r"\s+","",m.group("numero")); text=text[m.start():]; begun=True
        # Los decretos solo pueden citar números anteriores. Un encabezado
        # posterior marca el siguiente documento del recorte oficial; una
        # referencia a un número menor forma parte del texto objetivo.
        end=next((m for m in neighbor.finditer(text) if int(m.group(1))>n),None)
        if end:
            text=text[:end.start()]
            numero_vecino=int(end.group(1))
            if numero_vecino not in trimmed: trimmed.append(numero_vecino)
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
    out=[f"# {etiqueta} núm. {n:03d}-{year}\n\n",'!!! warning "Aviso"\n    LEY.DO no es una fuente oficial. Verifique este documento contra la fuente oficial indicada.\n    LEY.DO no ofrece asesoría legal.\n\n',"## Metadata\n\n",f"- Tipo de documento: {tipo}\n- Número: {n:03d}\n- Año: {year}\n- Título detectado: {t}\n- Fecha: {d.get('fecha_documento','')}\n- Gaceta oficial: {d.get('gaceta_oficial','')}\n- Institución fuente: {d.get('institucion_fuente','')}\n",f"- Fuente oficial: [{d.get('url_fuente_oficial','')}]({d.get('url_fuente_oficial','')})\n- Documento oficial: [{d.get('url_documento_consultoria_abrir','')}]({d.get('url_documento_consultoria_abrir','')})\n- Descarga oficial: [{d.get('url_documento_consultoria_descargar','')}]({d.get('url_documento_consultoria_descargar','')})\n",f"- Hash SHA256 del PDF: `{hpdf}`\n- Estado de revisión: pendiente_revision\n\n## Texto\n\n"]
    if pages:
        for i,page in enumerate(pages,1): out += [f"### Página {i} del PDF\n\n",page,"\n\n"]
    else: out += ["Texto pendiente de extracción: encabezado esperado no localizado.\n\n"]
    out += ["## Notas de revisión\n\n- Pendiente de revisión humana.\n",f"- Estado de extracción: `{state}`.\n","- Texto extraído automáticamente del PDF oficial y refluido para legibilidad; cotejar contra el PDF.\n"]
    if trimmed: out += ["- El PDF contenía fragmentos de decretos vecinos; se delimitaron usando sus encabezados oficiales.\n"]
    return "".join(out)

def run(repo,year,numbers,documentos_explicitos=None,inventario_path=None):
    inventario_path=inventario_path or repo/"fuentes"/f"consultoria_inventario_{year}_leyes_decretos.json"
    inv=json.loads(Path(inventario_path).read_text(encoding="utf-8")); registros=inv["documentos"]["decretos"]
    docs={}
    for d in registros:
        numero=nint(d.get("numero",""))
        if numero is not None: docs.setdefault(numero,[]).append(d)
    docs_por_id={str(d.get("document_id_consultoria")):d for d in registros}
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
        stem=f"decreto-{n:03d}-{year}"
        pdf=repo/"archivos"/"decretos"/str(year)/(stem+".pdf")
        md=repo/"docs"/"decretos"/str(year)/(stem+".md")
        js=repo/"datos"/"decretos"/str(year)/(stem+".json")
        if not pdf.exists() or not pdf.read_bytes().startswith(b"%PDF"): raise ValueError(f"PDF ausente/inválido: {pdf}")
        pages,trimmed,state,clase_encabezado,numero_encabezado=extract(pdf,n,str(year)[-2:]); hpdf=sha(pdf)
        rendiciones=[]
        for original in d.get("rendiciones_oficiales_relacionadas",[]):
            item=dict(original); ruta=repo/item.get("ruta_pdf_local","")
            if not ruta.is_file() or not ruta.read_bytes().startswith(b"%PDF"):
                raise ValueError(f"Rendición oficial ausente/inválida: {ruta}")
            calculado=sha(ruta); esperado_hash=item.get("sha256_pdf","")
            if esperado_hash and esperado_hash!=calculado:
                raise ValueError(f"Hash incorrecto para rendición oficial: {ruta}")
            item["sha256_pdf"]=calculado; rendiciones.append(item)
        formal=re.search(rf"(?im)^N[ÚU]MERO:\s*(0*{n}-\d{{2,4}})\b","\n".join(pages)); numero_formal=formal.group(1) if formal else ""; esperado=f"{n}-{str(year)[-2:]}"; discrepancia_numero=bool(numero_encabezado and numero_encabezado.lstrip("0")!=esperado); discrepancia_denominacion=clase_encabezado.lower()=="ec."; discrepancia=discrepancia_numero or discrepancia_denominacion
        fecha_fuente=d.get("fecha_documento",""); fecha_pdf=fecha_dado(pages,year); alertas=list(d.get("alertas_revision",[]))
        md_text=markdown(n,year,d,pages,hpdf,state,trimmed,clase_encabezado)
        if alertas:
            bloque="".join(f"- {item}\n" for item in alertas)
            md_text=md_text.replace("## Notas de revisión\n\n",f"## Notas de revisión\n\n{bloque}",1)
        if rendiciones:
            detalle=["- Rendiciones oficiales relacionadas:\n"]
            for item in rendiciones:
                detalle.append(f"  - ID `{item.get('document_id_consultoria','')}`: [{item.get('rol_archivistico','rendición oficial')}]({item.get('url_pdf_oficial','')}) — SHA256 `{item.get('sha256_pdf','')}`.\n")
            md_text=md_text.replace("- Hash SHA256 del PDF:","".join(detalle)+"- Hash SHA256 del PDF:",1)
        if fecha_pdf and fecha_fuente and fecha_pdf!=fecha_fuente:
            alerta_fecha=f"La metadata oficial consultada indica {fecha_fuente}, mientras el apartado DADO del PDF indica {fecha_pdf}. Se conservan ambos valores para revisión humana."
            if alerta_fecha not in alertas: alertas.append(alerta_fecha)
            md_text=md_text.replace(f"- Fecha: {fecha_fuente}\n",f"- Fecha: {fecha_fuente}\n- Fecha observada en texto PDF: {fecha_pdf}\n",1).replace("## Notas de revisión\n\n",f"## Notas de revisión\n\n- {alerta_fecha}\n",1)
        if discrepancia:
            partes=[]; metadata_extra=""
            if discrepancia_numero:
                partes.append(f"El encabezado sumario del PDF indica `{numero_encabezado}`, mientras la línea formal indica `{numero_formal or esperado}` y la metadata oficial corresponde a `{esperado}`."); metadata_extra+=f"- Número en el encabezado sumario del PDF: `{numero_encabezado}`\n- Número formal en el PDF: `{numero_formal or esperado}`\n"
            if discrepancia_denominacion:
                partes.append(f"La denominación visible del encabezado está truncada como `{clase_encabezado} No.` en el PDF, mientras la línea formal identifica el documento como `{numero_formal or esperado}`."); metadata_extra+=f"- Denominación visible del encabezado del PDF: `{clase_encabezado} No.`\n"
            alerta=" ".join(partes)+" Se conserva la discrepancia para revisión humana."
            if alerta not in alertas: alertas.append(alerta)
            md_text=md_text.replace(f"- Número: {n:03d}\n",f"- Número: {n:03d}\n{metadata_extra}",1).replace("## Notas de revisión\n\n",f"## Notas de revisión\n\n- {alerta}\n",1)
        md.parent.mkdir(parents=True,exist_ok=True); md.write_text(md_text,encoding="utf-8",newline="\n"); hmd=sha(md); tipo_documento="reglamento" if clase_encabezado.lower().startswith("regl") else "decreto"
        meta={"tipo_documento":tipo_documento,"categoria_inventario_fuente":"decretos","denominacion_encabezado_pdf":clase_encabezado,"numero":f"{n:03d}","anio":str(year),"titulo":title(pages,n,str(year)[-2:],year),"fecha":fecha_fuente,"gaceta_oficial":d.get("gaceta_oficial",""),"institucion_fuente":d.get("institucion_fuente",""),"url_fuente_oficial":d.get("url_fuente_oficial",""),"url_pdf_original":d.get("url_documento_consultoria_descargar",""),"url_documento_oficial":d.get("url_documento_consultoria_abrir",""),"document_id_consultoria":d.get("document_id_consultoria",""),"fecha_consulta":date.today().isoformat(),"ruta_pdf_local":f"archivos/decretos/{year}/{stem}.pdf","ruta_markdown":f"docs/decretos/{year}/{stem}.md","ruta_json":f"datos/decretos/{year}/{stem}.json","sha256_pdf_original":hpdf,"sha256_markdown":hmd,"estado_revision":"pendiente_revision","estado_publicacion":"normalizado","estado_extraccion":state,"fragmentos_decretos_vecinos_excluidos":trimmed,"commit_publicacion":"","notas":"Texto extraído automáticamente desde PDF oficial; verificar contra el PDF. Segmentación por encabezados cuando hubo documentos vecinos."}
        for campo in ("numero_registro_fuente","anio_metadata_fuente","inventario_origen","observacion_fecha_pdf"):
            if campo in d: meta[campo]=d[campo]
        if rendiciones: meta["rendiciones_oficiales_relacionadas"]=rendiciones
        if fecha_pdf and fecha_fuente and fecha_pdf!=fecha_fuente:
            meta.update({"fecha_metadata_fuente":fecha_fuente,"fecha_texto_pdf_detectada":fecha_pdf})
        if discrepancia:
            meta.update({"numero_encabezado_pdf":numero_encabezado,"numero_formal_pdf":numero_formal or esperado})
        if alertas:
            meta.update({"alertas_revision":alertas,"notas":" ".join(alertas)+" Texto extraído automáticamente desde PDF oficial; verificar contra el PDF."})
        js.parent.mkdir(parents=True,exist_ok=True); js.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
        print(f"OK {stem}: {len(pages)} página(s), PDF {hpdf[:12]}…, MD {hmd[:12]}…")
def main():
    p=argparse.ArgumentParser(); p.add_argument("--repo",type=Path,default=Path.cwd()); p.add_argument("--anio",type=int,required=True); p.add_argument("--numeros",required=True); p.add_argument("--documentos",default="",help="Mapeo numero=document_id_consultoria separado por comas"); a=p.parse_args()
    documentos={}
    for item in a.documentos.split(","):
        if item.strip():
            numero,document_id=item.split("=",1); documentos[int(numero)]=document_id.strip()
    run(a.repo.resolve(),a.anio,[int(x) for x in a.numeros.split(",")],documentos)
if __name__=="__main__": main()
