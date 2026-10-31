"""Explicit account/model diagnostic. No credential contents are recorded."""
from __future__ import annotations
import argparse
import json
import os
import secrets
import time
from pathlib import Path
from .model_client import RealClient,ModelError,load_environment
from .schemas import validate_normalization
from .agent import prompt
from .trace import Trace,write_json


def probe(output_dir):
    load_environment()
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    if (out/'result.json').exists(): raise ValueError('Choose a new probe output directory')
    trace=Trace(out/'trace.jsonl',{'model_mode':'real','purpose':'account_and_model_probe'})
    client=RealClient()
    errors=client.configuration_errors()
    if errors:
        result={'status':'not_run','configuration_errors':errors,'model_calls':0,
                'note':'未向服务商发送请求，不能确认账号或模型可用性。'}
        write_json(out/'result.json',result); return result
    main=os.getenv('LLM_MAIN_MODEL',os.getenv('LLM_MODEL','qwen-plus-2025-12-01'))
    fast=os.getenv('LLM_FAST_MODEL','qwen-flash-2025-07-28')
    count=0
    def request(model,messages,stage,**kw):
        nonlocal count
        count+=1; start=time.perf_counter()
        trace.add('model_request',stage=stage,requested_model=model,messages=messages,**kw)
        try:
            response=client.complete(model=model,messages=messages,stage=stage,**kw)
            trace.add('model_response',stage=stage,requested_model=model,**response,elapsed_ms=round((time.perf_counter()-start)*1000,3))
            return response
        except ModelError as exc:
            trace.add('model_error',stage=stage,requested_model=model,error={'code':exc.code,'message':str(exc)})
            raise
    results={}
    tools=[{'type':'function','function':{'name':'read_probe','description':'读取诊断标记，返回后请逐字输出标记。',
           'parameters':{'type':'object','properties':{},'additionalProperties':False,'required':[]}}}]
    try:
        messages=[{'role':'user','content':'请调用read_probe读取标记，拿到工具返回后只输出marker的值。'}]
        response=request(main,messages,'plus_tool_selection',tools=tools,tool_choice={'type':'function','function':{'name':'read_probe'}})
        calls=response['message'].get('tool_calls',[])
        if len(calls)!=1 or calls[0]['function']['name']!='read_probe':
            raise ModelError('PROBE_TOOL_SELECTION_FAILED','Plus未按诊断要求选择工具')
        token=secrets.token_hex(12)
        observation={'marker':token}
        trace.add('tool_result',stage='probe',tool='read_probe',observation=observation)
        messages.extend([response['message'],{'role':'tool','tool_call_id':calls[0]['id'],'content':json.dumps(observation)}])
        second=request(main,messages,'plus_observation',tools=tools,tool_choice='none')
        passed=(second['message'].get('content') or '').strip()==token
        results['plus']={'tool_call_and_observation_verified':passed,'requested_model':main,'response_model':second['response_model']}
    except (ModelError,ValueError,KeyError,TypeError) as exc:
        results['plus']={'passed':False,'error_code':getattr(exc,'code',type(exc).__name__),'message':str(exc)}
    question='星影协作标准版能导出PDF吗？'
    try:
        response=request(fast,[{'role':'system','content':prompt('P3').split('当前问题：')[0]},
            {'role':'user','content':json.dumps({'question':question,'history':[]},ensure_ascii=False)}],'flash_json',json_mode=True)
        value=validate_normalization(json.loads(response['message'].get('content') or ''),question)
        results['flash']={'json_valid':True,'requested_model':fast,'response_model':response['response_model'],'output':value}
    except (ModelError,ValueError,KeyError,TypeError) as exc:
        results['flash']={'passed':False,'error_code':getattr(exc,'code',type(exc).__name__),'message':str(exc)}
    passed=results.get('plus',{}).get('tool_call_and_observation_verified') and results.get('flash',{}).get('json_valid')
    result={'status':'passed' if passed else 'failed','model_calls':count,'results':results,
            'note':'仅验证账号、指定模型和消息协议；不代表业务验收通过。'}
    write_json(out/'result.json',result); return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args()
    result=probe(args.output_dir)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='passed' else 2


if __name__=='__main__': raise SystemExit(main())
