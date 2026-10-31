"""Small strict contracts; semantic support is evaluated separately."""
from __future__ import annotations
import re

MODEL_STATUSES = {'answered', 'needs_clarification', 'insufficient_evidence', 'tool_error'}
OUTPUT_FIELDS = {'answer','citations','gaps','status','reason_code','follow_up_question','decision_summary'}


def validate_input(value):
    if not isinstance(value, dict) or set(value) - {'question','history'}:
        raise ValueError('input accepts only question and history')
    if not isinstance(value.get('question'), str) or not value['question'].strip():
        raise ValueError('question must be nonempty text')
    history = value.get('history', [])
    if not isinstance(history, list):
        raise ValueError('history must be an array')
    for m in history:
        if not isinstance(m, dict) or set(m) != {'role','content'} or not isinstance(m['role'],str) or m['role'] not in {'user','assistant'} or not isinstance(m['content'], str):
            raise ValueError('history must contain user/assistant text messages only')
    return {'question':value['question'], 'history':history}


def validate_normalization(value, question):
    required = {'intent','original_question','normalized_query','keywords','known_context','missing_information'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('P3 fields invalid')
    if not isinstance(value['intent'],str) or value['intent'] not in {'knowledge_question','needs_context','chitchat'}:
        raise ValueError('P3 intent invalid')
    if value['original_question'] != question:
        raise ValueError('P3 changed original_question')
    query = value['normalized_query']
    if not isinstance(query, str) or not query.strip() or not isinstance(value['known_context'], dict):
        raise ValueError('P3 query/context invalid')
    for name in ('keywords','missing_information'):
        if not isinstance(value[name], list) or any(not isinstance(s, str) for s in value[name]):
            raise ValueError('P3 list invalid')
    # Conservative, deterministic guards only. This is not a semantic equivalence proof.
    protected = re.findall(r'\d+(?:[.\-/]\d+)*|标准版|专业版|企业版|免费版|试用版|不支持|不能|不要|不允许|不得|未满|至少|最多', question)
    if any(token not in query for token in protected):
        raise ValueError('P3 removed protected number, edition or condition')
    return value


def validate_output(value, evidence, corpus_hash):
    errors = []
    if not isinstance(value, dict) or set(value) != OUTPUT_FIELDS:
        return ['final JSON fields invalid']
    for key in ('answer','reason_code','follow_up_question','decision_summary'):
        if not isinstance(value[key], str): errors.append(key + ' must be text')
    if not value.get('answer'): errors.append('answer must be nonempty')
    if not isinstance(value['status'],str) or value['status'] not in MODEL_STATUSES: errors.append('invalid model status')
    if not isinstance(value['gaps'], list) or any(not isinstance(s,str) for s in value['gaps']):
        errors.append('gaps must be text array')
    elif value['status'] != 'answered' and not value['gaps']:
        errors.append('unfinished result must explain gaps')
    if value['status']=='needs_clarification' and not value['follow_up_question']:
        errors.append('clarification requires a question')
    citations = value['citations']
    if not isinstance(citations, list): return errors + ['citations must be array']
    if value['status']=='answered' and not citations:
        errors.append('answered requires read evidence citations')
    for c in citations:
        if not isinstance(c,dict) or set(c) != {'doc_id','version_date','chunk_id','quote'} or any(not isinstance(v,str) or not v for v in c.values()):
            errors.append('citation fields invalid'); continue
        found = evidence.get((c['doc_id'],c['chunk_id']))
        if not found:
            errors.append('citation was not read this request'); continue
        if c['version_date'] != found['version_date'] or found['corpus_hash'] != corpus_hash:
            errors.append('citation version/corpus mismatch')
        if c['quote'] not in found['text']:
            errors.append('quote is not a continuous substring of read text')
    return errors


def terminal(status, code, gap):
    return {'answer':gap,'citations':[],'gaps':[gap],'status':status,'reason_code':code,
            'follow_up_question':'','decision_summary':'程序根据执行或校验结果结束本次请求。'}
