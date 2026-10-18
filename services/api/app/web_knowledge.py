"""Bounded public medical reference search. Never accepts raw case/chat queries."""
import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

POLICY='grounded-public-web-reference-v1'
ENDPOINT='https://open.feedcoopapi.com/search_api/web_search'
# Original public institutions only. Provider ranking is not a medical approval.
HOSTS=('nhc.gov.cn','nhsa.gov.cn','cma.org.cn','pumch.cn','pkuph.cn',
       'bjmu.edu.cn','hjzyy.mil.cn','xasdjyy.cn','ghsrmyy.com',
       'orthoinfo.aaos.org','orthoinfo.org','nhs.uk','medlineplus.gov','mayoclinic.org','cancer.gov')
# Public generic vocabulary, not patient-derived search strings. Unknown names
# are not sent until an administrator extends this dictionary.
CONCEPTS=tuple(sorted(('肺炎','社区获得性肺炎','骨折','糖尿病','冠心病','腰椎间盘突出症',
 '股骨头缺血性坏死','股骨头坏死','高血压','心房颤动','心力衰竭','心肌梗死',
 '胆囊结石','胆囊炎','胆总管结石','阑尾炎','甲状腺结节','甲状腺癌','乳腺癌','乳腺结节',
 '肺结节','肺癌','胃癌','结肠癌','直肠癌','肝癌','胃炎','胃溃疡','十二指肠溃疡',
 '肾结石','输尿管结石','肾囊肿','慢性肾病','脑梗死','脑出血','短暂性脑缺血发作',
 '慢性阻塞性肺疾病','哮喘','支气管炎','肝硬化','脂肪肝','乙型肝炎','贫血',
 '白内障','青光眼','骨质疏松症','膝关节骨关节炎','类风湿关节炎','痛风','椎管狭窄',
 '髋关节置换术','髋关节置换','膝关节置换术','胆囊切除术','阑尾切除术',
 '甲状腺切除术','冠状动脉支架植入术','冠状动脉搭桥术','骨折切开复位内固定术',
 '椎间盘切除术','白内障手术','胃镜检查','肠镜检查','靶向治疗','化疗','放射治疗'),key=len,reverse=True))
PUBLIC_SYNONYMS={'乳腺恶性肿瘤':'乳腺癌','乳癌':'乳腺癌','骨质疏松':'骨质疏松症'}
TREATMENT_TERMS={'靶向治疗','化疗','放射治疗'}
ALIASES={'胆囊结石':('gallstones',),'胆囊切除术':('gallbladder removal','cholecystectomy'),
         '心房颤动':('atrial fibrillation',),'高血压':('hypertension','high blood pressure'),
         '甲状腺结节':('thyroid nodules',),'乳腺癌':('breast cancer',),
         '骨质疏松症':('osteoporosis',),'靶向治疗':('targeted therapy',),
         '化疗':('chemotherapy',),'放射治疗':('radiation therapy',)}
COST_TOPICS={
 '医保目录分类':('甲类 乙类 目录外 医保药品目录 含义',('甲类','乙类','医保药品目录','医保目录')),
 '医保个人负担':('医保 个人自费 个人自付 区别',('个人自费','个人自付','医保')),
 '医保起付线':('医保 起付线 含义',('起付线','起付标准')),
 '医保封顶线':('医保 封顶线 最高支付限额 含义',('封顶线','最高支付限额')),
 '医保异地就医':('医保 异地就医 备案 结算',('异地就医','异地结算')),
}

def chat_concepts(question):
    """Extract fixed public topics only; no raw message leaves the application."""
    topics=[]
    if re.search(r'甲类|乙类|丙类|甲乙丙|医保目录|药品目录',question):topics.append('医保目录分类')
    if re.search(r'个人自费|个人自付',question):topics.append('医保个人负担')
    if '起付线' in question:topics.append('医保起付线')
    if re.search(r'封顶线|最高支付限额',question):topics.append('医保封顶线')
    if '异地' in question and re.search(r'医保|就医|结算',question):topics.append('医保异地就医')
    result=[{'term':topic,'slot':'COST'} for topic in topics]
    for term in CONCEPTS:
        if term in question and not any(term in item['term'] for item in result):
            result.append({'term':term,'slot':'S11' if term in TREATMENT_TERMS or '术' in term or term.endswith('置换') else 'S1'})
    return result[:2]


def approved_url(url):
    try:
        p=urlparse(url)
        # Licensed encyclopedia content on NLM has distinct reuse restrictions.
        if (p.hostname or '').endswith('medlineplus.gov') and p.path.startswith('/ency/'):return False
        return (p.scheme in {'https','http'} and not p.username and not p.password
                and p.port in {None,80,443} and any(p.hostname==h or (p.hostname or '').endswith('.'+h) for h in HOSTS))
    except (TypeError,ValueError):return False


def appropriate_title(title):
    # This first reference vocabulary serves adult guidance. Do not mix in
    # pediatric/pregnancy-specific pages merely because the disease word matches.
    return isinstance(title,str) and not re.search(r'儿童|小儿|婴幼儿|婴儿|新生儿|孕妇|妊娠|\bchildren\b|pediatric|paediatric|pregnan',title,re.I)


def safe_concepts(fields,material):
    """Map quote-validated names to fixed public terms; no raw records or free queries."""
    candidates=fields.get('candidates',{})
    if isinstance(candidates,dict):candidates=candidates.get('candidates',[])
    names=re.findall(r'(?:姓名|患者姓名|病人姓名)\s*[:：]\s*([\u4e00-\u9fff]{2,8})',material)
    result=[]
    for c in candidates or []:
        kind=c.get('fact_type');raw=c.get('raw_value','');quote=c.get('evidence_quote','')
        if kind not in {'diagnosis','surgery','medication'} or c.get('assertion') not in {'present','suspected'}:continue
        if not isinstance(raw,str) or not quote or quote not in material or raw not in quote:continue
        if len(raw)>100 or re.search(r'姓名|某|先生|女士|患者|岁|地址|住院|电话|身份证|病历|帐号|账号|https?://',raw):continue
        if any(name in raw for name in names):continue
        vocabulary={**{term:term for term in CONCEPTS},**PUBLIC_SYNONYMS}
        occupied=[]
        for word,term in sorted(vocabulary.items(),key=lambda x:len(x[0]),reverse=True):
            for match in re.finditer(re.escape(word),raw):
                if any(match.start()<end and match.end()>start for start,end in occupied):continue
                occupied.append(match.span())
                if kind=='medication' and term not in TREATMENT_TERMS:continue
                item={'term':term,'slot':'S11' if term in TREATMENT_TERMS or kind=='surgery' else 'S1'}
                if item not in result:result.append(item)
    # Reserve the second query for a recorded treatment before other diagnoses.
    diagnosis=[item for item in result if item['slot']=='S1']
    treatment=[item for item in result if item['slot']=='S11']
    return [*diagnosis[:1],*treatment,*diagnosis[1:]]


def select_excerpt(content,terms,limit=2200):
    # Select whole original paragraphs/sentences, never paraphrase or cut a qualifier.
    if not isinstance(content,str) or len(content.strip())<80:return ''
    if re.search(r'忽略.{0,30}(?:指令|规则)|system\s*prompt|api.?key|密码|密钥',content,re.I):return ''
    if isinstance(terms,str):terms=[terms]
    relevant=lambda text:any(term.lower() in text.lower() for term in terms)
    if len(content)<=limit and relevant(content):return content.strip()
    chunks=[x.strip() for x in re.split(r'\n+',content) if x.strip()]
    if len(chunks)==1:chunks=re.findall(r'[^。！？]+[。！？]|[^。！？]+$',content)
    nearby={j for i,x in enumerate(chunks) if relevant(x) for j in range(max(0,i-1),min(len(chunks),i+3))}
    chosen=[];size=0
    for i,chunk in enumerate(chunks):
        added=len(chunk)+(1 if chosen else 0)
        if i in nearby and size+added<=limit:
            chosen.append(chunk);size+=added
    return '\n'.join(chosen) if size>=80 else ''


class WebKnowledge:
    def __init__(self,path=None,post=None,clock=time.time):
        self.path=Path(path or os.environ.get('ZHONGAN_WEB_SEARCH_CACHE','output_dir/web-search/cache.sqlite3'))
        self.post=post;self.clock=clock
        self.key=os.environ.get('VOLCENGINE_SEARCH_API_KEY','')
        self.mode=os.environ.get('VOLCENGINE_SEARCH_BILLING_MODE','')
        self.enabled=os.environ.get('ZHONGAN_WEB_SEARCH_ENABLED')=='1' and bool(self.key) and self.mode in {'payg','subscription'}
        try:
            self.daily=min(40,max(0,int(os.environ.get('VOLCENGINE_SEARCH_DAILY_LIMIT','40'))))
            self.per_report=min(2,max(0,int(os.environ.get('VOLCENGINE_SEARCH_PER_REPORT_LIMIT','2'))))
        except ValueError:self.enabled=False;self.daily=self.per_report=0

    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        conn=sqlite3.connect(self.path,timeout=2)
        conn.execute('CREATE TABLE IF NOT EXISTS references_cache (id TEXT PRIMARY KEY, document TEXT NOT NULL, expires REAL NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS searches (query_hash TEXT PRIMARY KEY, ids TEXT NOT NULL, expires REAL NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS daily_usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)')
        conn.commit()
        try:
            if os.name!='nt':self.path.chmod(0o600)
        except OSError:pass
        try:
            with conn:yield conn
        finally:conn.close()

    def resolve(self,ref):
        if not re.fullmatch(r'WEB-VOLC-[0-9a-f]{24}',ref):return None
        try:
            with self.db() as conn:
                row=conn.execute('SELECT document,expires FROM references_cache WHERE id=?',(ref,)).fetchone()
            if not row or row[1]<=self.clock():return None
            doc=json.loads(row[0])
            digest=hashlib.sha256((doc['source']+'\n'+doc['content']).encode()).hexdigest()
            if not approved_url(doc['source']) or not appropriate_title(doc.get('title')) or doc['entry_id']!='WEB-VOLC-'+digest[:24] or doc['version']!=POLICY+':'+digest:return None
            if doc.get('reference_policy')!=POLICY:return None
            return doc
        except (sqlite3.Error,OSError,ValueError,KeyError,TypeError):return None

    def search(self,concept):
        if not self.enabled:return {'status':'not_configured','results':[],'calls':0}
        # Public interface still enforces the concept contract even for internal callers.
        term=concept['term'];slot=concept['slot']
        cost=term in COST_TOPICS and slot=='COST'
        if not cost and safe_concepts({'candidates':[{'fact_type':'diagnosis' if slot=='S1' else 'surgery',
            'raw_value':term,'evidence_quote':term,'assertion':'present'}]},term)!=[concept]:
            return {'status':'unsafe_query','results':[],'calls':0}
        query=COST_TOPICS[term][0] if cost else term+' '+(ALIASES.get(term) or ('',))[0]+(' 医学解释' if slot=='S1' else ' 治疗含义' if term in TREATMENT_TERMS else ' 手术目的')
        query_hash=hashlib.sha256((POLICY+('|cost-v2|' if cost else '|')+query).encode()).hexdigest()
        now=self.clock();day=datetime.fromtimestamp(now,timezone(timedelta(hours=8))).date().isoformat()
        try:
            with self.db() as conn:
                cached=conn.execute('SELECT ids,expires FROM searches WHERE query_hash=?',(query_hash,)).fetchone()
                if cached and cached[1]>now:
                    docs=[self.resolve(ref) for ref in json.loads(cached[0])]
                    if all(docs):return {'status':'cached','results':docs,'calls':0}
                conn.execute('BEGIN IMMEDIATE')
                row=conn.execute('SELECT calls FROM daily_usage WHERE day=?',(day,)).fetchone()
                if (row[0] if row else 0)>=self.daily:return {'status':'daily_limit','results':[],'calls':0}
                conn.execute('INSERT INTO daily_usage VALUES (?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1',(day,))
                conn.commit()
            payload={'Query':query.strip(),'SearchType':'web','Count':12,'ContentFormats':'text',
                'Filter':{'NeedContent':True,'NeedUrl':True,'Sites':'nhsa.gov.cn' if cost else '|'.join(HOSTS)}}
            kwargs={'headers':{'Authorization':'Bearer '+self.key,'Content-Type':'application/json'},
                    'json':payload,'timeout':(5,15),'allow_redirects':False}
            if self.post:response=self.post(ENDPOINT,**kwargs)
            else:
                with requests.Session() as session:
                    session.trust_env=False;response=session.post(ENDPOINT,**kwargs)
            response.raise_for_status();data=response.json()
            if not isinstance(data,dict) or not isinstance(data.get('ResponseMetadata') or {},dict):raise ValueError('INVALID_SEARCH_RESPONSE')
            error=(data.get('ResponseMetadata') or {}).get('Error')
            if error:
                code=str(error.get('Code','unknown')) if isinstance(error,dict) else 'unknown'
                return {'status':'provider_error','error_code':code if re.fullmatch(r'\d{3,10}',code) else 'unknown','results':[],'calls':1}
            result=data.get('Result') or {}
            if not isinstance(result,dict):raise ValueError('INVALID_SEARCH_RESPONSE')
            docs=self.references(result.get('WebResults',[]),concept,now)
            expiry=now+((7 if cost else 30)*86400 if docs else 3600)
            with self.db() as conn:
                for doc in docs:
                    conn.execute('INSERT OR REPLACE INTO references_cache VALUES (?,?,?)',(doc['entry_id'],json.dumps(doc,ensure_ascii=False),expiry))
                conn.execute('INSERT OR REPLACE INTO searches VALUES (?,?,?)',(query_hash,json.dumps([d['entry_id'] for d in docs]),expiry))
            return {'status':'available' if docs else 'no_authoritative_results','results':docs,'calls':1}
        except (requests.RequestException,ValueError,KeyError,TypeError,sqlite3.Error,OSError):
            return {'status':'unavailable','results':[],'calls':1 if 'payload' in locals() else 0}

    def references(self,rows,concept,now):
        if not isinstance(rows,list):return []
        docs=[];seen=set();term=concept['term'];slot=concept['slot'];terms=list(COST_TOPICS[term][1]) if slot=='COST' and term in COST_TOPICS else [term,*ALIASES.get(term,())]
        if slot=='COST':
            def published_order(item):
                match=re.search(r'/art/(\d{4})/(\d{1,2})/(\d{1,2})/',str(item.get('Url',''))) if isinstance(item,dict) else None
                return tuple(map(int,match.groups())) if match else (0,0,0)
            rows=sorted(rows,key=published_order,reverse=True)
        for item in rows:
            if not isinstance(item,dict):continue
            url=item.get('Url');title=item.get('Title') or ''
            if not appropriate_title(title):continue
            title_match=any(t.lower() in title.lower() for t in terms) or slot=='COST' and bool(re.search(r'医保|药品',title))
            if slot=='COST' and re.search(r'征求意见|草案',title):continue
            if not approved_url(url) or url in seen or not title_match:continue
            content=select_excerpt(item.get('Content'),['甲类','乙类'] if term=='医保目录分类' else terms)
            if not content:continue
            if term=='医保目录分类' and not all(word in content for word in ('甲类','乙类')):continue
            digest=hashlib.sha256((url+'\n'+content).encode()).hexdigest()
            seen.add(url)
            date_match=re.search(r'/art/(\d{4})/(\d{1,2})/(\d{1,2})/',url)
            published=str(item.get('PublishTime') or '')[:40]
            if not published and date_match:published='-'.join(f'{int(value):0{4 if index==0 else 2}d}' for index,value in enumerate(date_match.groups()))
            docs.append({'entry_id':'WEB-VOLC-'+digest[:24],'title':title[:160],'content':content,
                'source':url,'source_path':url,'scope':('仅用于医保费用术语的一般解释，具体待遇须核对适用年份、地区和个人参保情况，不能直接推算报销或赔付。' if slot=='COST' else '仅用于该医学术语的一般解释；网络资料未获人工医学审核，不是本人的诊断或医嘱。'),
                'slot':slot,'disease_code':'TY','status':'unreviewed_web_reference',
                'version':POLICY+':'+digest,'reference_policy':POLICY,'use':'general_reference',
                'retrieval_provider':'volcengine','retrieved_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),
                'published_at':published,'concept':concept})
            if len(docs)>=2:break
        return docs


def supplement_knowledge(local,fields,material):
    service=WebKnowledge();results=list(local);events=[];attempts=0
    if not service.enabled:return results,{'status':'not_configured','calls':0,'events':[]}
    for concept in safe_concepts(fields,material):
        # A disease-pack match is not proof that this exact diagnosis/procedure is explained.
        if any(d.get('slot') in ({'S1','S2'} if concept['slot']=='S1' else {'S11','S2'})
               and concept['term'] in (d.get('title','')+' '+d.get('content','')) for d in local):continue
        if attempts>=service.per_report:break
        attempts+=1;found=service.search(concept)
        events.append({'status':found['status'],'calls':found['calls'],'result_count':len(found['results']),
                       'slot':concept['slot'],**({'error_code':found['error_code']} if found.get('error_code') else {})})
        results.extend(found['results'])
    return results,{'status':'checked','provider':'volcengine','calls':sum(e['calls'] for e in events),'events':events}
