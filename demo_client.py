"""A tiny local test client, not an official MCP SDK or an AI application."""
import json
from pathlib import Path
import subprocess
import sys


def main():
    root=Path(__file__).resolve().parent
    messages=[
        {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'local-demo','version':'1.0'}}},
        {'jsonrpc':'2.0','method':'notifications/initialized'},
        {'jsonrpc':'2.0','id':2,'method':'tools/list'},
        {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'plan_craft','arguments':{'target':'lantern','quantity':3,'inventory':{'plate':1,'ore':1}}}}
    ]
    result=subprocess.run([sys.executable,str(root/'server.py'),str(root/'examples/recipes.json')],
                          input=''.join(json.dumps(m)+'\n' for m in messages),text=True,encoding='utf-8',capture_output=True,timeout=10)
    if result.returncode:
        raise RuntimeError(result.stderr)
    responses=[json.loads(line) for line in result.stdout.splitlines()]
    if len(responses)!=3 or responses[0]['result']['protocolVersion']!='2025-11-25':
        raise RuntimeError('Unexpected initialization response')
    payload=responses[-1]['result']['structuredContent']
    if payload['base_needed']!={'ore':3,'shard':6}:
        raise RuntimeError('Unexpected crafting result')
    print(json.dumps(payload,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    sys.exit(main())
