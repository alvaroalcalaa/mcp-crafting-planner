import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from planner import Catalog, load_json
from server import Session, VERSION


RECIPES={'recipes':{'plate':{'yield':3,'inputs':{'ore':2}},'crystal':{'yield':2,'inputs':{'shard':3}},'lantern':{'yield':1,'inputs':{'plate':2,'crystal':1}}}}


def request(method,params=None,rid=1):
    return {'jsonrpc':'2.0','id':rid,'method':method,'params':{} if params is None else params}


def ready():
    s=Session(Catalog(RECIPES))
    s.handle(request('initialize',{'protocolVersion':VERSION,'capabilities':{},'clientInfo':{'name':'test','version':'1'}}))
    s.handle({'jsonrpc':'2.0','method':'notifications/initialized'})
    return s


class CraftTests(unittest.TestCase):
    def test_demo_batch_rounding_and_stock(self):
        r=Catalog(RECIPES).plan('lantern',3,{'plate':1,'ore':1})
        self.assertEqual(r['base_needed'],{'ore':3,'shard':6})
        self.assertEqual(r['remaining_inventory'],{'crystal':1,'plate':1})
        self.assertEqual(r['inventory_used'],{'ore':1,'plate':1})

    def test_existing_target_needs_no_crafting(self):
        r=Catalog(RECIPES).plan('lantern',2,{'lantern':3,'ore':4})
        self.assertEqual(r['craft_steps'],[])
        self.assertEqual(r['remaining_inventory'],{'lantern':1,'ore':4})

    def test_raw_target(self):
        self.assertEqual(Catalog(RECIPES).plan('ore',5,{'ore':2})['base_needed'],{'ore':3})

    def test_shared_ingredients_aggregate_before_rounding(self):
        c=Catalog({'recipes':{'a':{'yield':1,'inputs':{'x':1,'y':1}},'x':{'yield':1,'inputs':{'plate':1}},'y':{'yield':1,'inputs':{'plate':1}},'plate':{'yield':3,'inputs':{'ore':2}}}})
        r=c.plan('a')
        self.assertEqual(r['base_needed'],{'ore':2})
        self.assertEqual(r['remaining_inventory'],{'plate':1})
        self.assertEqual(sum(s['batches'] for s in r['craft_steps'] if s['item']=='plate'),1)

    def test_steps_replay_with_resource_conservation(self):
        initial={'plate':1,'ore':1}
        c=Catalog(RECIPES)
        r=c.plan('lantern',3,initial)
        stock=copy.deepcopy(initial)
        for k,v in r['base_needed'].items():
            stock[k]=stock.get(k,0)+v
        for step in r['craft_steps']:
            for k,v in step['inputs'].items():
                stock[k]-=v
                self.assertGreaterEqual(stock[k],0)
            stock[step['item']]=stock.get(step['item'],0)+step['produced']
        stock['lantern']-=3
        self.assertEqual({k:v for k,v in stock.items() if v},r['remaining_inventory'])
        self.assertEqual(initial,{'plate':1,'ore':1})

    def test_deterministic_recipe_order(self):
        a=Catalog(RECIPES).plan('lantern',4)
        b=Catalog({'recipes':dict(reversed(list(RECIPES['recipes'].items())))}).plan('lantern',4)
        self.assertEqual(a,b)

    def test_cycles_rejected(self):
        with self.assertRaises(ValueError):
            Catalog({'recipes':{'a':{'yield':1,'inputs':{'b':1}},'b':{'yield':1,'inputs':{'a':1}}}})

    def test_invalid_quantities_unknown_items_and_overflow(self):
        c=Catalog(RECIPES)
        for target,n,stock in [('lantern',True,{}),('lantern',0,{}),('unknown',1,{}),('lantern',1,{'missing':1}),('lantern',1000000000,{})]:
            with self.assertRaises(ValueError):
                c.plan(target,n,stock)

    def test_bad_recipe(self):
        for recipe in ({'yield':0,'inputs':{'ore':1}}, {'yield':1,'inputs':{}}, {'yield':1,'inputs':{'ore':True}}):
            with self.assertRaises(ValueError):
                Catalog({'recipes':{'a':recipe}})

    def test_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.json'
            p.write_text('{"recipes":{},"recipes":{}}')
            with self.assertRaises(ValueError):
                load_json(p)

    def test_initialization_and_list(self):
        s=Session(Catalog(RECIPES))
        self.assertIn('error',s.handle(request('tools/list')))
        s=ready()
        names=[t['name'] for t in s.handle(request('tools/list'))['result']['tools']]
        self.assertEqual(names,['list_recipes','plan_craft'])
        self.assertEqual(s.handle(request('ping'))['result'],{})

    def test_unknown_method_tool_and_invalid_args(self):
        s=ready()
        self.assertEqual(s.handle(request('bad'))['error']['code'],-32601)
        self.assertEqual(s.handle(request('tools/call',{'name':'bad'}))['error']['code'],-32602)
        r=s.handle(request('tools/call',{'name':'plan_craft','arguments':{'target':'lantern','quantity':True}}))
        self.assertTrue(r['result']['isError'])
        self.assertIsNone(s.handle({'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':1}}))

    def test_structured_result_and_text_agree(self):
        r=ready().handle(request('tools/call',{'name':'plan_craft','arguments':{'target':'lantern'}}))['result']
        self.assertFalse(r['isError'])
        self.assertEqual(json.loads(r['content'][0]['text']),r['structuredContent'])

    def test_real_stdio_process_parse_error_then_tool_call(self):
        root=Path(__file__).resolve().parent
        packets=[request('initialize',{'protocolVersion':VERSION,'capabilities':{},'clientInfo':{'name':'test','version':'1'}}),{'jsonrpc':'2.0','method':'notifications/initialized'},request('tools/list',rid=2),request('tools/call',{'name':'plan_craft','arguments':{'target':'lantern','quantity':3,'inventory':{'plate':1,'ore':1}}},3)]
        input_text='{bad json}\n'+''.join(json.dumps(p)+'\n' for p in packets)
        p=subprocess.run([sys.executable,str(root/'server.py'),str(root/'examples/recipes.json')],input=input_text,text=True,encoding='utf-8',capture_output=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        r=[json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual(len(r),4)
        self.assertEqual(r[0]['error']['code'],-32700)
        self.assertEqual(r[1]['result']['protocolVersion'],VERSION)
        self.assertEqual(r[-1]['result']['structuredContent']['base_needed'],{'ore':3,'shard':6})
        self.assertEqual(p.stderr,'')

    def test_demo_client_and_cli(self):
        root=Path(__file__).resolve().parent
        for args in ([str(root/'demo_client.py')],[str(root/'planner.py'),str(root/'examples/recipes.json'),'lantern','--quantity','3','--inventory',str(root/'examples/inventory.json')]):
            p=subprocess.run([sys.executable]+args,capture_output=True,text=True,encoding='utf-8',timeout=10)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(json.loads(p.stdout)['remaining_inventory'],{'crystal':1,'plate':1})


if __name__=='__main__':
    unittest.main()
