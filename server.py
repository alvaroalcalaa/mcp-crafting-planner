"""Small MCP stdio server targeting protocol revision 2025-11-25 only."""
import argparse
import json
from pathlib import Path
import sys
from planner import Catalog, LIMIT, load_json, unique_object

VERSION = '2025-11-25'
MAX_LINE = 262144
ID_SCHEMA = {'type':'string','pattern':'^[a-zA-Z0-9_-]{1,64}$'}
TOOLS = [
    {'name':'list_recipes','description':'Lista recetas y materiales base del catálogo local cargado.',
     'inputSchema':{'type':'object','properties':{},'additionalProperties':False}},
    {'name':'plan_craft','description':'Calcula lotes, materiales base adicionales y sobrantes. No cambia el inventario.',
     'inputSchema':{'type':'object','properties':{'target':ID_SCHEMA,'quantity':{'type':'integer','minimum':1,'maximum':LIMIT},
        'inventory':{'type':'object','propertyNames':ID_SCHEMA,'additionalProperties':{'type':'integer','minimum':0,'maximum':LIMIT}}},
        'required':['target'],'additionalProperties':False}}
]
for tool in TOOLS:
    tool['annotations'] = {'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False}


class Session:
    def __init__(self, catalog):
        self.catalog, self.phase = catalog, 'new'

    def handle(self, msg):
        rid = msg.get('id') if isinstance(msg,dict) else None
        def error(code, text):
            return {'jsonrpc':'2.0','id':rid if type(rid) in (str,int) else None,'error':{'code':code,'message':text}}
        if not isinstance(msg,dict) or msg.get('jsonrpc')!='2.0' or not isinstance(msg.get('method'),str):
            return error(-32600,'Invalid request')
        if 'id' in msg and (type(rid) not in (str,int)):
            return error(-32600,'Invalid request ID')
        method, params = msg['method'], msg.get('params',{})
        if 'id' not in msg:
            if method=='notifications/initialized' and self.phase=='initializing':
                self.phase='ready'
            return None
        if not isinstance(params,dict):
            return error(-32602,'params must be an object')
        if method=='initialize':
            if self.phase!='new':
                return error(-32600,'Already initialized')
            info=params.get('clientInfo')
            if not isinstance(params.get('protocolVersion'),str) or not isinstance(params.get('capabilities'),dict) or not isinstance(info,dict) or not isinstance(info.get('name'),str) or not isinstance(info.get('version'),str):
                return error(-32602,'Invalid initialize parameters')
            self.phase='initializing'
            result={'protocolVersion':VERSION,'capabilities':{'tools':{'listChanged':False}},
                    'serverInfo':{'name':'mcp-crafting-planner','version':'1.0.0'}}
        elif method=='ping':
            result={}
        elif self.phase!='ready':
            return error(-32000,'Send initialize and notifications/initialized first')
        elif method=='tools/list':
            if params.get('cursor') is not None:
                return error(-32602,'Pagination is not supported')
            result={'tools':TOOLS}
        elif method=='tools/call':
            name, args = params.get('name'), params.get('arguments',{})
            if name not in ('plan_craft','list_recipes'):
                return error(-32602,'Unknown tool')
            try:
                if not isinstance(args,dict):
                    raise ValueError('arguments debe ser un objeto')
                if name=='list_recipes':
                    if args:
                        raise ValueError('list_recipes no acepta argumentos')
                    payload={'recipes':self.catalog.recipes,'base_items':sorted(self.catalog.items-self.catalog.recipes.keys())}
                else:
                    if set(args)-{'target','quantity','inventory'} or not isinstance(args.get('target'),str):
                        raise ValueError('Se requiere target y solo se aceptan quantity e inventory adicionales')
                    payload=self.catalog.plan(args['target'],args.get('quantity',1),args.get('inventory',{}))
                result={'content':[{'type':'text','text':json.dumps(payload,ensure_ascii=False)}],
                        'structuredContent':payload,'isError':False}
            except ValueError as exc:
                result={'content':[{'type':'text','text':str(exc)}],'isError':True}
        else:
            return error(-32601,'Method not found')
        return {'jsonrpc':'2.0','id':rid,'result':result}


def serve(catalog):
    session=Session(catalog)
    while True:
        line=sys.stdin.buffer.readline(MAX_LINE+1)
        if not line:
            break
        if len(line)>MAX_LINE:
            print('Línea de entrada demasiado grande; se cierra la sesión',file=sys.stderr)
            return 2
        try:
            msg=json.loads(line.decode('utf-8'),object_pairs_hook=unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite number')))
            response=session.handle(msg)
        except (ValueError,UnicodeError,RecursionError):
            response={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
        if response is not None:
            print(json.dumps(response,ensure_ascii=False,allow_nan=False),flush=True)
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('catalog',type=Path)
    args=parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8',newline='\n')
    try:
        return serve(Catalog(load_json(args.catalog)))
    except (OSError,ValueError,RecursionError) as exc:
        print('Error de catálogo: '+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())
