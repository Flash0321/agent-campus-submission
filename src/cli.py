from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from .agent import Agent,AgentConfig,ROOT
from .model_client import load_environment


def main():
    load_environment()
    p=argparse.ArgumentParser(description='第3题 企业知识问答 Agent')
    p.add_argument('--mode',choices=['real','mock'],default='mock')
    p.add_argument('--profile',choices=['single','split'],default=os.getenv('MODEL_PROFILE','single'))
    inputs=p.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--input',type=Path); inputs.add_argument('--question')
    p.add_argument('--corpus',type=Path,default=ROOT/'data/variants/single_source.json')
    p.add_argument('--output-dir',type=Path)
    p.add_argument('--retrieval-mode',choices=['original','dual'],default='dual')
    p.add_argument('--max-model-calls',type=int,default=8)
    p.add_argument('--max-tool-calls',type=int,default=6)
    p.add_argument('--fault-file',type=Path,help='Testing only: local tool fault injection JSON')
    args=p.parse_args()
    try:
        input=json.loads(args.input.read_text(encoding='utf-8')) if args.input else {'question':args.question}
        fault=json.loads(args.fault_file.read_text(encoding='utf-8')) if args.fault_file else None
        config=AgentConfig(mode=args.mode,profile=args.profile,retrieval_mode=args.retrieval_mode,
             max_model_calls=args.max_model_calls,max_tool_calls=args.max_tool_calls,
             main_model=os.getenv('LLM_MAIN_MODEL',os.getenv('LLM_MODEL','qwen-plus-2025-12-01')),
             fast_model=os.getenv('LLM_FAST_MODEL','qwen-flash-2025-07-28'))
        output=args.output_dir or ROOT/'examples'/args.mode/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        result=Agent(config,args.corpus,fault=fault).run(input,output)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2 if result['status'] in {'tool_error','step_limit','invalid_output'} else 0
    except (ValueError,OSError) as exc:
        p.error(str(exc))


if __name__=='__main__': raise SystemExit(main())
