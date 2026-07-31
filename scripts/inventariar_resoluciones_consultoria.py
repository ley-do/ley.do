#!/usr/bin/env python
"""Inventaría resoluciones desde la consulta oficial de Consultoría Jurídica.
No descarga ni verifica PDFs: FileManagement permanece como enlace candidato oficial.
"""
from __future__ import annotations
import argparse, html, http.cookiejar, json, re, urllib.parse, urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

BASE="https://www.consultoria.gov.do"
CONSULTA=f"{BASE}/consulta/"
ESTADO="detectado_en_consulta_oficial_pendiente_verificacion_pdf"

class Table(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.rows=[]; self.cells=[]; self.cell=None; self.inrow=False
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="tr": self.inrow=True; self.cells=[]
        elif self.inrow and tag=="td": self.cell={"text":[],"title":a.get("title", ""),"hrefs":[]}
        elif self.cell is not None and tag=="a" and a.get("href"): self.cell["hrefs"].append(a["href"])
    def handle_endtag(self, tag):
        if tag=="td" and self.cell is not None: self.cells.append(self.cell); self.cell=None
        elif tag=="tr" and self.inrow:
            if len(self.cells)>=6: self.rows.append(self.cells)
            self.inrow=False; self.cells=[]
    def handle_data(self, data):
        if self.cell is not None: self.cell["text"].append(data)

def clean(value): return re.sub(r"\s+", " ", " ".join(value) if isinstance(value,list) else str(value)).strip()
def iso(value):
    m=re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})",value)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""

def fetch(year):
    jar=http.cookiejar.CookieJar(); opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    initial=opener.open(urllib.request.Request(CONSULTA,headers={"User-Agent":"LEY.DO inventory/1.0"}),timeout=45).read().decode("utf-8","replace")
    m=re.search(r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"',initial)
    if not m: raise RuntimeError("Token antifalsificación ausente en consulta oficial")
    fields={"__RequestVerificationToken":m.group(1),"DocumentTypeCode":"7","DocumentCategory":"0","DocumentNumber":"","DocumentTitle":"","GacetaOficial":"","PublicationYearOperator":"1","PublicationYear":str(year),"PublicationYearEnd":"","EmisionDateOperator":"1","EmisionDate":"","EmisionDateEnd":"","President":"0","Consultor":"0","Institution":"0","Length":"10000"}
    req=urllib.request.Request(f"{BASE}/Consulta/Home/Search?Length=10000",data=urllib.parse.urlencode(fields).encode(),headers={"User-Agent":"LEY.DO inventory/1.0","X-Requested-With":"XMLHttpRequest","Content-Type":"application/x-www-form-urlencoded; charset=UTF-8"})
    page=opener.open(req,timeout=90).read().decode("utf-8","replace")
    parser=Table(); parser.feed(page)
    out=[]; seen=set()
    for cells in parser.rows:
        numero=clean(cells[1]["text"]); title=clean(cells[2]["title"] or cells[2]["text"]); fecha=clean(cells[4]["text"])
        links=cells[5]["hrefs"]; open_link=next((x for x in links if "managementType=1" in x),""); download=next((x for x in links if "managementType=2" in x),"")
        ident=re.search(r"documentId=(\d+)",open_link or download)
        if not numero or not ident or ident.group(1) in seen: continue
        did=ident.group(1); seen.add(did)
        out.append({"tipo_documento":"resolucion","tipo_documento_fuente":clean(cells[0]["text"]),"numero":numero,"anio":str(year),"titulo":title,"gaceta_oficial":clean(cells[3]["text"]),"fecha_documento":fecha,"fecha_documento_iso":iso(fecha),"institucion_fuente":"Consultoría Jurídica del Poder Ejecutivo","url_fuente_oficial":CONSULTA,"url_documento_consultoria_abrir":urllib.parse.urljoin(BASE,html.unescape(open_link)),"url_documento_consultoria_descargar":urllib.parse.urljoin(BASE,html.unescape(download)),"document_id_consultoria":did,"url_pdf_original":"","fecha_consulta":date.today().isoformat(),"estado_inventario":ESTADO,"observaciones":"Detectado mediante la consulta oficial. El enlace de descarga aún no se ha descargado ni validado como PDF original."})
    return out

def make_md(data):
    docs=data["documentos"]; summary=data["resumen_por_anio"]
    lines=["# Inventario oficial de resoluciones 2016–2026","",'!!! warning "Aviso"',"    LEY.DO no es una fuente oficial. Este inventario no certifica exhaustividad, vigencia ni validez legal.","    Cada registro debe verificarse contra la fuente oficial y el PDF original antes de normalizarse.","","## Fuente oficial consultada","",f"- {CONSULTA}","","## Alcance","","Registros identificados como **Resoluciones** en la consulta oficial de la Consultoría Jurídica del Poder Ejecutivo.","Los enlaces de descarga son candidatos oficiales: no se presentan todavía como PDFs verificados.","","## Resumen por año","","| Año | Resoluciones detectadas |","|---:|---:|"]
    for year in sorted(summary,reverse=True): lines.append(f"| {year} | {summary[year]} |")
    lines.extend(["","## Registros",""])
    for year in sorted(summary,reverse=True):
        lines.extend([f"### {year}","","| Número | Fecha | Gaceta | Título | Estado |","|---|---|---|---|---|"])
        for d in (x for x in docs if x["anio"]==year):
            title = d["titulo"].replace("|", "\\|")
            lines.append(f"| {d['numero']} | {d['fecha_documento'] or '—'} | {d['gaceta_oficial'] or '—'} | {title} | {d['estado_inventario']} |")
        lines.append("")
    lines.extend(["## Nota documental","","- No se infiere vigencia, efecto jurídico ni relación entre resoluciones.","- La normalización posterior conservará la URL oficial, PDF validado, hashes y estado `pendiente_revision`.",""])
    return "\n".join(lines)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--inicio",type=int,default=2016); ap.add_argument("--fin",type=int,default=2026); ap.add_argument("--salida",type=Path,required=True); args=ap.parse_args()
    if args.inicio>args.fin: ap.error("--inicio no puede superar --fin")
    docs=[]; summary={}
    for year in range(args.inicio,args.fin+1):
        rows=fetch(year); docs.extend(rows); summary[str(year)]=len(rows); print(f"{year}: {len(rows)} resoluciones",flush=True)
    data={"tipo_inventario":"resoluciones_consultoria_juridica","fecha_consulta":date.today().isoformat(),"alcance":"Inventario de registros identificados como Resoluciones en la consulta oficial de la Consultoría Jurídica del Poder Ejecutivo.","advertencia":"No certifica exhaustividad, vigencia ni validez legal. Los enlaces de descarga requieren verificación de PDF antes de normalizarse.","fuentes_oficiales_consultadas":[CONSULTA],"resumen_por_anio":summary,"total_documentos_detectados":len(docs),"documentos":docs}
    args.salida.parent.mkdir(parents=True,exist_ok=True); args.salida.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); args.salida.with_suffix(".md").write_text(make_md(data),encoding="utf-8")
    print(f"Total: {len(docs)}")
if __name__=="__main__": main()
