import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.reconciliar_decretos_consultoria import main, reconcile


def record(numero, document_id, year="2018"):
    return {
        "tipo_documento": "decreto", "numero": numero, "anio": year,
        "titulo": f"Registro {document_id}", "gaceta_oficial": "", "fecha_documento": "01/01/2018",
        "institucion_fuente": "Consultoría Jurídica del Poder Ejecutivo",
        "url_fuente_oficial": "https://www.consultoria.gov.do/consulta/",
        "url_documento_consultoria_abrir": f"https://www.consultoria.gov.do/Consulta/Home/FileManagement?documentId={document_id}&managementType=1",
        "url_documento_consultoria_descargar": f"https://www.consultoria.gov.do/Consulta/Home/FileManagement?documentId={document_id}&managementType=2",
        "document_id_consultoria": document_id,
    }


class ReconciliarDecretosTests(unittest.TestCase):
    def test_cli_vincula_hashes_de_inventario_y_decisiones(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory_path=root/"inventario.json"; decisions_path=root/"decisiones.json"; output_path=root/"reconciliado.json"
            inventory={"documentos":{"decretos":[record("4-18","a")]}}; decisions={"schema_version":"1.0","anio":2018,"fecha_reconciliacion":"2026-07-29"}
            inventory_path.write_text(json.dumps(inventory),encoding="utf-8"); decisions_path.write_text(json.dumps(decisions),encoding="utf-8")
            self.assertEqual(main(["--inventario",str(inventory_path),"--decisiones",str(decisions_path),"--salida",str(output_path),"--anio","2018"]),0)
            output=json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(output["sha256_inventario_original"],hashlib.sha256(inventory_path.read_bytes()).hexdigest())
            self.assertEqual(output["sha256_decisiones_reconciliacion"],hashlib.sha256(decisions_path.read_bytes()).hexdigest())
            self.assertEqual(list(root.glob(output_path.name+".*.tmp")),[])

    def test_falla_si_identidad_duplicada_no_tiene_decision(self):
        inventory={"documentos":{"decretos":[record("4-18","a"),record("04-18","b")]}}
        with self.assertRaisesRegex(ValueError,"decisión.*4"): reconcile(inventory,2018,{"schema_version":"1.0","anio":2018,"fecha_reconciliacion":"2026-07-29"})

    def test_preserva_rendiciones_y_fuentes_contextuales(self):
        inventory={"documentos":{"decretos":[record("4-18","a"),record("04-18","b"),record("381-17","old"),record("169","atypical")]}}
        decisions={"schema_version":"1.0","anio":2018,"fecha_reconciliacion":"2026-07-29","identidades":{"4":{"canonico":"a","alertas_revision":["Se preservan dos rendiciones oficiales."],"rendiciones":[
            {"document_id_consultoria":"a","rol_archivistico":"pdf_canonico_publicado_en_gaceta","ruta_pdf_local":"archivos/decretos/2018/decreto-004-2018.pdf","url_pdf_oficial":"https://www.consultoria.gov.do/Consulta/Home/FileManagement?documentId=a&managementType=2","sha256_pdf":"a"*64,"capa_texto":True,"paginas":2},
            {"document_id_consultoria":"b","rol_archivistico":"rendicion_prepublicacion_complementaria","ruta_pdf_local":"archivos/decretos/2018/decreto-004-2018-fuente-b.pdf","url_pdf_oficial":"https://www.consultoria.gov.do/Consulta/Home/FileManagement?documentId=b&managementType=2","sha256_pdf":"b"*64,"capa_texto":True,"paginas":2},
        ]}}}
        reconciled=reconcile(inventory,2018,decisions)
        self.assertEqual(reconciled["resumen"]["registros_fuente"],4); self.assertEqual(reconciled["resumen"]["identidades_documentales"],1)
        self.assertEqual(reconciled["resumen"]["rendiciones_adicionales"],1); self.assertEqual(reconciled["resumen"]["fuentes_contextuales"],2)
        canonical=reconciled["documentos"]["decretos"][0]; self.assertEqual(canonical["document_id_consultoria"],"a"); self.assertEqual(canonical["sha256_pdf"],"a"*64); self.assertEqual(len(canonical["rendiciones_oficiales_relacionadas"]),2)
        roles={row["document_id_consultoria"]:row["rol_reconciliacion"] for row in reconciled["registros_fuente"]}
        self.assertEqual(roles["a"],"canonico"); self.assertEqual(roles["b"],"rendicion_complementaria"); self.assertEqual(roles["old"],"fuente_contextual_fuera_de_anio"); self.assertEqual(roles["atypical"],"fuente_contextual_atipica")

    def test_rechaza_schema_de_decisiones_incompatible(self):
        inventory={"documentos":{"decretos":[record("4-18","a")]}}
        with self.assertRaisesRegex(ValueError,"schema_version"):
            reconcile(inventory,2018,{"schema_version":"999","anio":2018})

    def test_rechaza_fecha_de_reconciliacion_no_iso(self):
        inventory={"documentos":{"decretos":[record("4-18","a")]}}
        with self.assertRaisesRegex(ValueError,"fecha_reconciliacion"):
            reconcile(inventory,2018,{"schema_version":"1.0","anio":2018,"fecha_reconciliacion":"no-es-fecha"})

    def test_rechaza_id_contextual_que_tambien_es_canonico(self):
        inventory={"documentos":{"decretos":[record("4-18","a")]}}
        decisions={"schema_version":"1.0","anio":2018,"fecha_reconciliacion":"2026-07-29","identidades":{"4":{"canonico":"a"}},"fuentes_contextuales":{"a":{"rol_reconciliacion":"fuente_contextual_atipica"}}}
        with self.assertRaisesRegex(ValueError,"contradictoria.*a"):
            reconcile(inventory,2018,decisions)

    def test_falla_si_rendicion_no_coincide_con_fuente(self):
        inventory={"documentos":{"decretos":[record("4-18","a"),record("04-18","b")]}}
        decisions={"schema_version":"1.0","anio":2018,"fecha_reconciliacion":"2026-07-29","identidades":{"4":{"canonico":"a","rendiciones":[
            {"document_id_consultoria":"a","rol_archivistico":"pdf_canonico","ruta_pdf_local":"archivos/decretos/2018/decreto-004-2018.pdf","url_pdf_oficial":"https://www.consultoria.gov.do/otro.pdf","sha256_pdf":"a"*64,"capa_texto":True,"paginas":2},
            {"document_id_consultoria":"b","rol_archivistico":"rendicion_complementaria","ruta_pdf_local":"archivos/decretos/2018/decreto-004-2018-fuente-b.pdf","url_pdf_oficial":"https://www.consultoria.gov.do/Consulta/Home/FileManagement?documentId=b&managementType=2","sha256_pdf":"b"*64,"capa_texto":True,"paginas":2},
        ]}}}
        with self.assertRaisesRegex(ValueError,"URL.*a"): reconcile(inventory,2018,decisions)


if __name__=="__main__": unittest.main()
