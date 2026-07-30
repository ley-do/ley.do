import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import fitz

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from scripts.auditar_decretos_consultoria import audit
from scripts.procesar_decretos_consultoria import generate_index


def make_pdf(text):
    doc=fitz.open(); page=doc.new_page(); page.insert_text((72,72),text,fontsize=9); data=doc.tobytes(); doc.close(); return data


class AuditorDecretosTests(unittest.TestCase):
    def make_corpus(self,root,formal="1-19",alerts=None,dado_year=2019):
        record={"numero":"1-19","anio":"2019","identidad_documental_numero":1,"document_id_consultoria":"id-1","institucion_fuente":"Consultoria Juridica","url_fuente_oficial":"https://www.consultoria.gov.do/","url_documento_consultoria_descargar":"https://www.consultoria.gov.do/1.pdf","url_documento_consultoria_abrir":"https://www.consultoria.gov.do/1","titulo":"Prueba","fecha_documento":"01/01/2019","gaceta_oficial":"10900"}
        inventory={"resumen":{"total_registros_fuente":1,"total_identidades_documentales":1},"registros_fuente":[record],"documentos":{"decretos":[record]}}
        inventory_path=root/"fuentes/inventario.json"; inventory_path.parent.mkdir(parents=True); inventory_path.write_text(json.dumps(inventory),encoding="utf-8")
        pdf=root/"archivos/decretos/2019/decreto-001-2019.pdf"; md=root/"docs/decretos/2019/decreto-001-2019.md"; js=root/"datos/decretos/2019/decreto-001-2019.json"
        pdf.parent.mkdir(parents=True); md.parent.mkdir(parents=True); js.parent.mkdir(parents=True)
        dado_words="dos mil dieciocho" if dado_year==2018 else "dos mil diecinueve"
        pdf.write_bytes(make_pdf(f"Dec. No. 1-19\nNUMERO: {formal}\nDADO en Santo Domingo, a un (1) dia del mes de enero del ano {dado_words} ({dado_year})."))
        md.write_text("# Decreto 001-2019\n\nLEY.DO no es una fuente oficial.\nLEY.DO no ofrece asesoría legal.\n\n## Metadata\n\n## Texto\n\nTexto.\n\n## Notas de revisión\n",encoding="utf-8")
        metadata={"tipo_documento":"decreto","numero":"001","anio":"2019","document_id_consultoria":"id-1","institucion_fuente":"Consultoria Juridica","url_fuente_oficial":"https://www.consultoria.gov.do/","url_pdf_original":"https://www.consultoria.gov.do/1.pdf","url_documento_oficial":"https://www.consultoria.gov.do/1","ruta_pdf_local":"archivos/decretos/2019/decreto-001-2019.pdf","ruta_markdown":"docs/decretos/2019/decreto-001-2019.md","ruta_json":"datos/decretos/2019/decreto-001-2019.json","sha256_pdf_original":hashlib.sha256(pdf.read_bytes()).hexdigest(),"sha256_markdown":hashlib.sha256(md.read_bytes()).hexdigest(),"estado_revision":"pendiente_revision","estado_publicacion":"normalizado","estado_extraccion":"extraido_desde_pdf_oficial","fecha":"01/01/2019","gaceta_oficial":"10900","fecha_texto_pdf_detectada":"01/01/2019","estado_fecha_texto_pdf":"detectada","numero_formal_pdf":formal,"fragmentos_decretos_vecinos_excluidos":[]}
        if alerts: metadata["alertas_revision"]=alerts
        js.write_text(json.dumps(metadata),encoding="utf-8"); generate_index(root,inventory_path,2019); return inventory_path

    def test_audita_un_corpus_minimo_valido(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root); report=audit(root,inventory,2019)
            self.assertEqual(report["errores"],[]); self.assertEqual(report["resumen"]["identidades_documentales"],1); self.assertEqual(report["resumen"]["filas_indice"],1)

    def test_falla_si_fecha_del_json_contradice_fuente_reconciliada(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root); path=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(path.read_text(encoding="utf-8")); metadata["fecha"]="31/12/1999"; path.write_text(json.dumps(metadata),encoding="utf-8")
            report=audit(root,inventory,2019)
            self.assertTrue(any("fecha" in error.lower() and "fuente" in error.lower() for error in report["errores"]))

    def test_falla_si_gaceta_del_json_contradice_fuente_reconciliada(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root); path=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(path.read_text(encoding="utf-8")); metadata["gaceta_oficial"]="99999"; path.write_text(json.dumps(metadata),encoding="utf-8")
            report=audit(root,inventory,2019)
            self.assertTrue(any("gaceta" in error.lower() and "fuente" in error.lower() for error in report["errores"]))

    def test_falla_si_numero_formal_discrepa_sin_alerta(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root,formal="0-19"); report=audit(root,inventory,2019)
            self.assertTrue(any("formal" in error.lower() for error in report["errores"]))


    def test_conserva_anio_dado_observado_si_discrepancia_esta_documentada(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root,dado_year=2018); path=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(path.read_text(encoding="utf-8")); metadata["fecha_texto_pdf_detectada"]="01/01/2018"; metadata["fecha_metadata_fuente"]="01/01/2019"; metadata["alertas_revision"]=["La metadata oficial indica 2019 y el DADO observado indica 2018; se conservan ambos valores."]; path.write_text(json.dumps(metadata),encoding="utf-8")
            report=audit(root,inventory,2019)
            self.assertEqual(report["errores"],[]); self.assertEqual(report["resumen"]["discrepancias_fecha_documentadas"],1)


    def test_falla_si_json_dado_contradice_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root,dado_year=2019); path=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(path.read_text(encoding="utf-8")); metadata["fecha_texto_pdf_detectada"]="01/01/2018"; metadata["fecha_metadata_fuente"]="01/01/2019"; metadata["alertas_revision"]=["La metadata oficial indica 2019 y el DADO observado indica 2018; se conservan ambos valores."]; path.write_text(json.dumps(metadata),encoding="utf-8")
            report=audit(root,inventory,2019)
            self.assertTrue(any("dado" in error.lower() and "pdf" in error.lower() for error in report["errores"]))


if __name__=="__main__": unittest.main()
