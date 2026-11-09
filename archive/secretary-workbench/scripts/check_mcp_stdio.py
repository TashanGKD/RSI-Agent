"""Explicit isolated MCP discovery and missing-config refusal, never a live tool call."""
import argparse,asyncio,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
async def check():
 from mcp import Client,StdioServerParameters
 with tempfile.TemporaryDirectory() as d:
  env={k:v for k,v in os.environ.items() if k in ['PATH','LANG','PYTHONPATH']};env['SECRETARY_SENDER_WORKSPACE']=d
  results=[]
  for mode,expected in [('--mcp-sender',{'request_context','wechat_operation','upload_file','save_asset','wechat_source','mac_file','mac_download','report_to_origin'}),('--mcp-caller',{'sender_assign','sender_status'})]:
   async with Client(StdioServerParameters(command=sys.executable,args=[str(ROOT/'host/aup-sender/sender_work_tools.py'),mode],env=env),read_timeout_seconds=10) as client:
    out=await client.list_tools();tools=out.tools if hasattr(out,'tools') else out;names={x.name for x in tools};assert names==expected
    if mode=='--mcp-sender':
     r=await client.call_tool('wechat_operation',{'request':{'op':'capabilities'}})
     assert getattr(r,'is_error',getattr(r,'isError',False)), 'unconfigured SDK must fail before host execution'
    results.append({'mode':mode,'toolCount':len(names),'names':sorted(names)})
  print(json.dumps({'discovery':results,'missingConfigRefused':True,'nativeModelAndWeChatCalls':0}))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');a=p.parse_args()
 if not a.execute:p.print_help();return
 asyncio.run(check())
if __name__=='__main__':main()
