import unittest
from copy import deepcopy
from uuid import uuid4
from pydantic import ValidationError
from services.api.app.cost_breakdown import CostBreakdown,build_cost_breakdown,cost_fact,cost_pairs,report_cost_context,validate_cost_sources
from services.api.app.llm_extractor import ModelCostLine,ModelExtraction,validate_evidence_quotes
from services.api.app.contracts.core import ExtractedFact
from services.api.app.event_builder import build_events
from services.api.app.insight_detector import deterministic_candidates

class CostBreakdownTests(unittest.TestCase):
    def row(self,text,doc=None,page=0,version=1):
        return {'text':text,'evidence_id':uuid4(),'document_id':doc or uuid4(),
                'document_version':version,'page_index':page}

    def test_categories_and_payments_are_evidence_bound_and_never_summed(self):
        row=self.row('医疗总费用：1,000.50元\n药品费：200.50元\n检查费：300元\n个人自付：100元\n个人自费：50元\n个人账户支付：50元\n现金支付：100元\n商业保险后净支出：90元')
        result=build_cost_breakdown([row])
        self.assertEqual(len(result.fields),8)
        labels={f.source_label:f for f in result.fields}
        self.assertEqual(labels['药品费'].amount.value.amount_minor,20050)
        self.assertEqual(labels['个人自费'].role,'payment_component')
        self.assertEqual(labels['个人账户支付'].amount.value.amount_minor,5000)
        self.assertEqual(labels['商业保险后净支出'].amount.value.amount_minor,9000)
        self.assertIsNone(result.item_sum_minor)
        self.assertIsNone(result.self_paid_ratio)
        self.assertEqual(result.completeness_status,'not_established')
        self.assertTrue(all(f.document_id==row['document_id'] and f.amount.evidence_ids==[row['evidence_id']] for f in result.fields))
        self.assertTrue(all(f.amount.confidence_score is not None for f in result.fields))
        fact=cost_fact([row])
        ExtractedFact(field_id=fact.pop('fact_id'),case_id=uuid4(),run_id=uuid4(),**fact)

    def test_repeated_sources_do_not_add_money_and_conflicts_preserve_alternatives(self):
        doc=uuid4()
        a,b=self.row('药品费：100元',doc),self.row('药品费：100元',doc)
        field=build_cost_breakdown([a,b]).fields[0]
        self.assertEqual(field.amount.value.amount_minor,10000)
        self.assertEqual(set(field.amount.evidence_ids),{a['evidence_id'],b['evidence_id']})
        c=self.row('药品费：200元',doc)
        fact=cost_fact([a,b,c])
        field=build_cost_breakdown([a,b,c]).fields[0]
        self.assertEqual(field.amount.status,'conflict')
        self.assertIsNone(field.amount.value)
        self.assertEqual({alt.value.amount_minor for alt in field.amount.alternatives},{10000,20000})
        _,events,relations=build_events(uuid4(),[fact])
        self.assertEqual(events[0]['assertion'],'unknown')
        self.assertEqual(relations[0]['status'],'indeterminate')

    def test_documents_versions_pages_and_unknown_scopes_are_not_combined(self):
        doc=uuid4()
        rows=[self.row('药品费：100元',doc),self.row('药品费：200元',doc,page=1),
              self.row('药品费：300元',doc,version=2),self.row('药品费：400元')]
        self.assertEqual(len(build_cost_breakdown(rows).fields),4)
        rows=[{'evidence_id':uuid4(),'text':'总费用：1000元'}, {'evidence_id':uuid4(),'text':'明细合计：900元'}]
        self.assertEqual(deterministic_candidates(rows),[])
        rows=[self.row('总费用：1000元',doc),self.row('明细合计：900元',doc,page=1)]
        self.assertEqual(deterministic_candidates(rows),[])
        rows[1]['page_index']=0
        self.assertEqual(len(deterministic_candidates(rows)),1)

    def test_unsupported_money_formats_and_estimates_remain_missing(self):
        for text in ['预计药品费：100元','药品费：100元至200元','药品费：-100元','药品费：1,00元',
            '药品费：100.123元','药品费：100美元','药品费：10%','药品费：1e3元','药品费：不详']:
            self.assertEqual(list(cost_pairs(text)),[],text)
            self.assertEqual(cost_fact([self.row(text)])['status'],'missing')
        self.assertEqual(cost_fact([])['evidence_ids'],[])
        field=build_cost_breakdown([self.row('合计：100元')]).fields[0]
        self.assertEqual(field.role,'unclassified_total')

    def test_model_cost_line_must_preserve_source_label_amount_and_context(self):
        row=self.row('药品费：100元；检查费：200元')
        lines=[{'label':'药品费','amount_minor':20000,'currency':'CNY','evidence_quote':row['text']},
               {'label':'虚构费','amount_minor':10000,'currency':'CNY','evidence_quote':row['text']}]
        baseline=build_cost_breakdown([row])
        result=build_cost_breakdown([row],lines)
        self.assertEqual([(f.source_label,f.amount.value.amount_minor) for f in result.fields],
                         [(f.source_label,f.amount.value.amount_minor) for f in baseline.fields])
        estimate=self.row('预计药品费：100元')
        line={'label':'药品费','amount_minor':10000,'currency':'CNY','evidence_quote':'药品费：100元'}
        self.assertEqual(build_cost_breakdown([estimate],[line]).fields,[])
        validated=ModelExtraction(candidates=[],cost_lines=[{**line,'evidence_quote':'药品费：100元'}])
        checked=validate_evidence_quotes({'candidates':validated.model_dump()},'未记录费用')
        self.assertEqual(checked['candidates']['cost_lines'],[])
        with self.assertRaises(ValidationError): ModelCostLine(**{**line,'amount_minor':True})
        with self.assertRaises(ValidationError): ModelCostLine(**{**line,'amount_minor':100.5})

    def test_output_contract_rejects_forged_amount_role_or_source_scope(self):
        row=self.row('药品费：100元')
        original=build_cost_breakdown([row]).model_dump(mode='json')
        for path,value in [('amount',{'amount_minor':99900,'currency':'CNY'}),('scope_ref','other-scope'),
                           ('role','total')]:
            raw=deepcopy(original)
            if path=='amount': raw['fields'][0]['amount']['value']=value
            else: raw['fields'][0][path]=value
            with self.assertRaises(ValidationError): CostBreakdown.model_validate(raw)
        context=report_cost_context([row])
        self.assertEqual(context['fields'][0]['source_quotes'],['药品费：100元'])
        self.assertEqual(context['fields'][0]['value']['amount_minor'],10000)
        self.assertNotIn('evidence_id',str(context))

    def test_release_source_recheck_rejects_wrong_scope_quote_and_stripped_estimate(self):
        row=self.row('药品费：100元')
        breakdown=build_cost_breakdown([row])
        actual={str(row['evidence_id']):{**row,'text_value':row['text']}}
        validate_cost_sources(breakdown,actual)
        for changes in ({'text_value':'药品费：200元'}, {'document_id':uuid4()},
                        {'document_version':2}, {'page_index':1}, {'text_value':'预计药品费：100元'}):
            changed={str(row['evidence_id']):{**actual[str(row['evidence_id'])],**changes}}
            with self.assertRaises(ValueError): validate_cost_sources(breakdown,changed)
