"""Offline deterministic demo policy. NOT evidence of real model intelligence.

Reads only question/history and real tool observations, never cases or gold labels.
"""
from __future__ import annotations
import json
import re
import uuid


class MockClient:
    def __init__(self,behavior=None): self.behavior=behavior

    def complete(self,*,model,messages,stage=None,**kwargs):
        data=json.loads(next(m['content'] for m in messages if m['role']=='user'))
        question=data['question']
        if stage=='P3':
            history=' '.join(m['content'] for m in data.get('history',[]) if m['role']=='user')
            edition='专业版' if '专业版' in question else ('标准版' if '标准版' in question else ('专业版' if '专业版' in history else '标准版'))
            query=question
            if any(x in question for x in ('报账','垫付')): query=question+' 报销 提交申请 期限'
            if any(x in question for x in ('PDF','专业版','标准版','它')):
                query='星影协作'+edition+' 导出 PDF '+question
            result={'intent':'knowledge_question','original_question':question,'normalized_query':query,
                    'keywords':[],'known_context':{},'missing_information':[]}
            return self.response(model,result)
        if stage=='P5':
            return self.response(model,{'answer':'离线Mock不执行语义修复。','citations':[],'gaps':['需要真实模型验证修复能力'],
                'status':'insufficient_evidence','reason_code':'mock_repair','follow_up_question':'',
                'decision_summary':'Mock仅用于流程测试。'})
        normalized=(data.get('normalization') or {}).get('normalized_query',question)
        observations=[]
        names={c['id']:c['function']['name'] for m in messages if m['role']=='assistant' for c in m.get('tool_calls',[])}
        for m in messages:
            if m['role']=='tool': observations.append((names.get(m['tool_call_id']),json.loads(m['content'])))
        searches=[v for n,v in observations if n=='search_documents']
        reads=[v for n,v in observations if n=='read_document']
        if self.behavior=='always_search' or not searches:
            return self.tool(model,'search_documents',{'queries':list(dict.fromkeys([question,normalized]))[:2],'top_k':5,'reason':'查找问题相关的原文位置（离线Mock策略）。'})
        expense=any(x in normalized for x in ('报销','报账','垫付'))
        product=any(x in normalized for x in ('PDF','标准版','专业版'))
        edition='专业版' if '专业版' in normalized else '标准版'
        candidates=[]
        for search in searches:
            for item in search.get('results',[]):
                text=item.get('snippet','')
                relevant=(expense and '天内' in text) or (product and edition in text and 'PDF' in text)
                if relevant and item not in candidates: candidates.append(item)
        successful={v['doc_id']:v for v in reads if v.get('ok')}
        for item in candidates:
            if item['doc_id'] not in successful:
                failures=[v for v in reads if not v.get('ok')]
                if len(failures)>=2:
                    return self.final(model,'tool_error','读取工具持续失败，无法核实制度。',[],['必要原文无法读取'],'tool_failure')
                return self.tool(model,'read_document',{'doc_id':item['doc_id'],'chunk_ids':[item['chunk_id']],
                    'reason':'读取原文确认依据；如遇临时故障则重试（离线Mock策略）。'})
        evidence=[]
        for v in successful.values():
            for c in v['chunks']:
                evidence.append({'doc_id':v['doc_id'],'version_date':v['version_date'],'chunk_id':c['chunk_id'],'quote':c['text']})
        numbers=set(re.findall(r'(\d+)天', ' '.join(c['quote'] for c in evidence)))
        if expense and len(numbers)>1:
            if len(searches)<2:
                return self.tool(model,'search_documents',{'queries':['报销制度 适用范围 优先级 替代','报销制度 裁决公告'],'top_k':5,'reason':'两份原文期限不同，查找裁决依据（离线Mock策略）。'})
            return self.final(model,'needs_clarification','当前资料存在冲突：'+ '；'.join(c['doc_id']+'：'+c['quote'] for c in evidence),
                evidence,['缺少制度适用范围与优先级说明'],'document_conflict','请确认适用制度，或提供具有裁决效力的公告。')
        if evidence:
            return self.final(model,'answered','依据当前读取的资料：'+'；'.join(c['quote'] for c in evidence),evidence,[],'supported_by_read_evidence')
        if len(searches)<2:
            return self.tool(model,'search_documents',{'queries':[normalized+' 制度 规定'],'top_k':5,'reason':'未找到支持条款，补充检索（离线Mock策略）。'})
        return self.final(model,'insufficient_evidence','当前知识库未找到能够回答此问题的原文。',[],['缺少该问题对应的制度或产品说明'],'no_supporting_evidence')

    @staticmethod
    def response(model,value):
        return {'message':{'role':'assistant','content':json.dumps(value,ensure_ascii=False)},'response_model':'mock:'+model,'usage':{}}

    def tool(self,model,name,arguments):
        return {'message':{'role':'assistant','content':None,'tool_calls':[{'id':'mock_'+uuid.uuid4().hex[:12],
            'type':'function','function':{'name':name,'arguments':json.dumps(arguments,ensure_ascii=False)}}]},'response_model':'mock:'+model,'usage':{}}

    def final(self,model,status,answer,citations,gaps,reason_code,follow_up=''):
        return self.response(model,{'answer':answer,'citations':citations,'gaps':gaps,'status':status,'reason_code':reason_code,
            'follow_up_question':follow_up,'decision_summary':'根据本轮工具观察执行离线演示策略；不证明真实模型决策效果。'})
