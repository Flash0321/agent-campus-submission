"""Bailian Chat Completions over HTTP. No hidden retries or SDK state."""
from __future__ import annotations
import json
import os
import re
import urllib.request
import urllib.error
from urllib.parse import urlparse
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_environment():
    load_dotenv(ROOT / '.env', override=False)


def scrub(value):
    if isinstance(value, dict):
        return {k:scrub(v) for k,v in value.items() if k.lower() not in {'authorization','api_key','llm_api_key','reasoning_content'}}
    if isinstance(value, list): return [scrub(v) for v in value]
    if isinstance(value, str):
        for name in ('LLM_API_KEY','DASHSCOPE_API_KEY'):
            secret=os.environ.get(name)
            if secret: value=value.replace(secret,'[REDACTED]')
        return re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[REDACTED]', value)
    return value


class ModelError(Exception):
    def __init__(self, code, message):
        self.code=code
        super().__init__(scrub(message))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RealClient:
    def __init__(self):
        load_environment()
        self.key=os.environ.get('LLM_API_KEY','')
        self.base=os.environ.get('LLM_BASE_URL','').rstrip('/')
        self.timeout=float(os.environ.get('LLM_TIMEOUT_SECONDS','45'))
        self.opener=urllib.request.build_opener(NoRedirect)

    def configuration_errors(self):
        errors=[]
        if not self.key: errors.append('LLM_API_KEY 未配置')
        if not self.base: errors.append('LLM_BASE_URL 未配置')
        else:
            parsed=urlparse(self.base)
            host=parsed.hostname or ''
            if parsed.scheme!='https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
                errors.append('LLM_BASE_URL 必须是无鉴权信息的 HTTPS 地址')
            if not (host=='dashscope.aliyuncs.com' or host.endswith('.cn-beijing.maas.aliyuncs.com')):
                errors.append('请配置百炼北京地域端点；本项目不向其他地域发送密钥')
        if not 0 < self.timeout <= 300: errors.append('LLM_TIMEOUT_SECONDS 须在0到300之间')
        return errors

    def complete(self, *, model, messages, tools=None, json_mode=False, tool_choice=None, stage=None):
        errors=self.configuration_errors()
        if errors: raise ModelError('CONFIGURATION_MISSING', '; '.join(errors))
        payload={'model':model,'messages':messages,'temperature':0.1,'enable_thinking':False,
                 'stream':False,'max_tokens':2048}
        if tools:
            payload.update(tools=tools, parallel_tool_calls=False, tool_choice=tool_choice or 'auto')
        if json_mode: payload['response_format']={'type':'json_object'}
        url=self.base if self.base.endswith('/chat/completions') else self.base+'/chat/completions'
        req=urllib.request.Request(url,data=json.dumps(payload,ensure_ascii=False).encode(),
            headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'},method='POST')
        try:
            with self.opener.open(req,timeout=self.timeout) as response:
                result=json.load(response)
        except urllib.error.HTTPError as exc:
            code='HTTP_'+str(exc.code)
            try:
                body=json.loads(exc.read())
                detail=body.get('error',{})
                message=str(detail.get('message',code))[:400]
                remote_code=detail.get('code')
                if isinstance(remote_code,str): code += ':'+remote_code[:80]
            except Exception: message=code
            raise ModelError(code,message) from None
        except (urllib.error.URLError,TimeoutError,OSError) as exc:
            raise ModelError('NETWORK_ERROR', '模型连接失败或超时：'+type(exc).__name__) from None
        except (ValueError,TypeError):
            raise ModelError('INVALID_API_RESPONSE','模型服务未返回有效JSON') from None
        try:
            m=result['choices'][0]['message']
            if not isinstance(m,dict): raise ValueError()
            message={k:m[k] for k in ('role','content','tool_calls') if k in m}
            message['role']='assistant'
            return {'message':message,'response_model':result.get('model',model),'usage':result.get('usage',{}),
                    'finish_reason':result['choices'][0].get('finish_reason')}
        except (KeyError,IndexError,TypeError,ValueError):
            raise ModelError('INVALID_API_RESPONSE','模型响应缺少有效message') from None
