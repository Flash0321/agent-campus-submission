from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from .model_client import scrub


def write_json(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(scrub(value),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


class Trace:
    def __init__(self, path, common):
        self.path=Path(path); self.common=common; self.events=[]
        self.path.write_text('',encoding='utf-8')

    def add(self,event,**fields):
        item=scrub({**self.common,'event':event,'step':len(self.events)+1,
             'time':datetime.now(timezone.utc).isoformat(),**fields})
        self.events.append(item)
        with self.path.open('a',encoding='utf-8') as f:
            f.write(json.dumps(item,ensure_ascii=False)+'\n')
        return item


def write_summary(path, events, result):
    """Readable audit generated only after the actual events exist."""
    lines=['# 实际执行摘要', '', '本文件由本次 Trace 生成；简要依据不是模型内部思维过程。', '',
           '| 步骤 | 工具与参数 | 实际返回摘要 | 后续模型动作 | 简要依据 |',
           '|---|---|---|---|---|']
    def cell(value):
        if not isinstance(value,str): value=json.dumps(value,ensure_ascii=False)
        return value.replace('|','\\|').replace('\n',' ')[:700]
    for index,event in enumerate(events):
        if event.get('event')!='tool_result': continue
        later=next((e for e in events[index+1:] if e.get('event')=='model_response' and e.get('stage')=='P4'),None)
        action='没有后续主模型响应（见最终状态）'; reason=''
        if later:
            message=later.get('message',{}); calls=message.get('tool_calls') or []
            if calls:
                action=', '.join(str(c['function'].get('name','无效工具名')) for c in calls if isinstance(c,dict) and isinstance(c.get('function'),dict))
                try: reason=json.loads(calls[0]['function']['arguments']).get('reason','')
                except (ValueError,TypeError,KeyError,AttributeError): reason='工具参数无效'
            else:
                try:
                    final=json.loads(message.get('content') or '')
                    action='提出最终结果：'+str(final.get('status'))
                    reason=final.get('decision_summary','')
                except (ValueError,TypeError,AttributeError): action='提出最终文本，待结构校验'
        args=event.get('arguments')
        if isinstance(args,dict): args={k:v for k,v in args.items() if k!='reason'}
        lines.append('| '+' | '.join(cell(v) for v in [event['step'],event.get('tool','')+' '+cell(args),event.get('summary',''),action,reason])+' |')
    lines+=['', '最终状态：`'+result['status']+'`','',result['answer'],'',
            '来源模式：`'+str(events[0].get('model_mode','unknown'))+'`。Mock只验证程序流程。']
    Path(path).write_text('\n'.join(lines)+'\n',encoding='utf-8')
