"""Compute auditable profiles from an authorized claim-feature export, never invented inputs."""
import argparse
import json
from pathlib import Path
from services.api.app.quality_profiles import QualityInput, ProfileMatchRequest, build_profiles, match_profiles


def evaluate(data, requests):
    snapshot=build_profiles(data)
    matches=[]
    for request in requests:
        results=match_profiles(snapshot,**request.model_dump(exclude={'needs'}),needs=request.needs)
        matches.append({'request':request.model_dump(mode='json'),'candidates':results,
            'coverage':{'mapped_hospitals':len({p['entity_id'] for p in snapshot['profiles'] if p['entity_type']=='hospital' and
                p['cohort_filters']['disease_group']==request.disease_group.value}),
                'five_computable_hospitals':len({p['entity_id'] for p in snapshot['profiles'] if p['entity_type']=='hospital' and
                p['cohort_filters']['disease_group']==request.disease_group.value and sum(m['computable'] for m in p['metrics'])>=5}),
                'five_comparable_hospitals':len({p['entity_id'] for p in snapshot['profiles'] if p['entity_type']=='hospital' and
                    all(p['cohort_filters'][key]==value for key,value in request.model_dump(exclude={'needs'}).items()) and
                    sum(m['comparison_allowed'] for m in p['metrics'])>=5}),
                'valid_two_reason_hospitals':len({r['candidate_id'] for r in results if r['entity_type']=='hospital' and r['eligible'] and len(r['match_reasons'])>=2}),
                'ranked_hospitals':len({r['candidate_id'] for r in results if r['entity_type']=='hospital' and r['ranking_allowed']})}})
    return {'snapshot':snapshot,'matches':matches,'official_kr4_verified':False,
            'limitations':['输入来源、授权和医学标注真实性需要上游权威核验；CLI本身不证明其真实',
                           '费用水平不是疗效或综合质量；删一观测区间不是置信区间',
                           '当前是特征包计算入口，尚未接入在线推荐权限/快照库/患者界面']}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--requests',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=QualityInput.model_validate_json(args.input.read_text(encoding='utf-8-sig'))
    requests=[ProfileMatchRequest.model_validate(r) for r in json.loads(args.requests.read_text(encoding='utf-8-sig'))]
    result=evaluate(data,requests)
    content=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with args.output.open('x',encoding='utf-8') as output:
            output.write(content)
    except FileExistsError:
        if args.output.read_text(encoding='utf-8')!=content:
            raise SystemExit('Output exists with a different snapshot; write a new artifact')
    print(json.dumps({'snapshot_id':result['snapshot']['snapshot_id'],'profiles':len(result['snapshot']['profiles']),
                      'official_kr4_verified':False},ensure_ascii=False))


if __name__=='__main__':
    main()
