import type {ChatSnapshot} from './types';

export type EncounterSummary={diagnosis?:string;hospital?:string;period?:string;kind?:string;documentCount?:number;source?:'material'|'intake'};

function labelled(text:string,labels:string) {
  const match=text.replace(/\*\*/g,'').match(new RegExp(`(?:^|[\\n\\r\\s，。；])(?:${labels})[：:]\\s*([^\\n\\r。；;]+)`));
  const value=match?.[1].split(/\s+(?:医院|就诊日期|住院时间|诊断|科室|姓名|年龄|性别|入院日期|出院日期)[：:]/)[0].trim();
  return value&&value.length<=100?value:undefined;
}
/** Use explicit material labels, preserving uncertainty and negative qualifiers. */
export function encounterSummary(snapshot:ChatSnapshot,evidence:string[]=[]):EncounterSummary {
  const material=snapshot.material_report?.status==='available'?snapshot.material_report:undefined;
  const texts=[...evidence,...(material?.sections?.flatMap(section=>section.items.map(item=>item.text))||[])];
  const summary:EncounterSummary={documentCount:material?.document_count};
  for(const text of texts){
    summary.diagnosis??=labelled(text,'出院诊断|入院诊断|主要诊断|临床诊断|诊断名称|诊断|就诊原因');
    summary.hospital??=labelled(text,'就诊医院|医疗机构名称|医疗机构|医院名称|医院');
    summary.period??=labelled(text,'就诊日期|就医日期|住院时间');
    if(!summary.hospital){
      summary.hospital=text.split(/[\n\r]/).map(line=>line.trim()).find(line=>/^[\u4e00-\u9fffA-Za-z（）()·\s]{2,40}(?:医院|卫生院|卫生服务中心)$/.test(line));
    }
  }
  if(summary.diagnosis)summary.source='material';
  // The claim form is explicit user input, so keep its provenance visible.
  for(const turn of snapshot.turns){
    const json=turn.question.match(/用户填写的信息：(\{[^\n]*?\})；材料分类：/)?.[1];
    if(!json)continue;
    try{
      const input=JSON.parse(json);
      if(!summary.diagnosis&&typeof input.diagnosis==='string'&&input.diagnosis.trim()){
        summary.diagnosis=input.diagnosis.trim();summary.source='intake';
      }
      if(!summary.period&&typeof input.start==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(input.start)){
        summary.period=input.start+(typeof input.end==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(input.end)?` 至 ${input.end}`:'');
      }
      if(typeof input.kind==='string'&&['住院医疗','门急诊医疗'].includes(input.kind))summary.kind=input.kind;
    }catch{/* Legacy free text does not become a medical summary. */}
  }
  return summary;
}
