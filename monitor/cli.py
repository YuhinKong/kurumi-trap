"""桌面启动与自检入口，所有操作使用当前项目的虚拟环境。"""
import argparse
import importlib.metadata
import json
import sys
from pathlib import Path
from .config import ROOT,load
from .store import Store
from .market import Provider,now

def selftest():
    cfg=load()
    result=dict(status='环境检查通过（未请求真实行情）',python=sys.version.split()[0],project=str(ROOT),
                watchlist=cfg['watchlist'],packages={})
    for name in ('akshare','streamlit','plotly','pandas','requests','pytest'):
        result['packages'][name]=importlib.metadata.version(name)
    Store('demo').put('selftest',dict(time=now().isoformat()))
    return result

def probe(cfg=None,store=None,all_sources=False):
    cfg=cfg or load(); store=store or Store()
    provider=Provider(store,cfg|{'retries':1})
    report=dict(time=now().isoformat(),python=sys.version.split()[0],stocks=[],sources=[])
    for code in cfg['watchlist']:
        row=dict(code=code)
        try:
            frame=provider.daily(code)
            row.update(history_source=frame.attrs['source'],history_rows=len(frame),latest_date=str(frame.date.iloc[-1].date()),
                history_stale=frame.attrs['stale'],history_sufficient=frame.attrs.get('history_sufficient'),
                weekly_rows=frame.attrs.get('complete_weekly_rows'),ohlcv_valid=True)
        except Exception as e: row['history_error']=str(e)
        quote=provider.quote(code)
        if quote:
            row.update(price=quote['price'],quote_source=quote['source'],bar_time=quote['bar_time'],fresh=quote.get('fresh',False),
                quality=quote['quality'],age_seconds=quote['data_age_seconds'],from_cache=quote['from_cache'])
            cross=provider.cross_validate(code,quote)
            row.update(cross_status=cross['status'],cross_reason=cross.get('reason'),cross_difference=cross.get('difference'))
        else: row.update(fresh=False,quote_error='全部快照来源失败，详见接口日志')
        report['stocks'].append(row)
        if all_sources:
            for source in provider.sources:
                item=dict(code=code,source=source.name)
                try:
                    frame,meta=source.daily(code,now())
                    verified=provider.validator.history(frame,code,source.name,source.origin,meta,now(),provider.calendar())
                    item.update(available=True,rows=len(verified),latest=str(verified.date.iloc[-1].date()),from_cache=meta['from_cache'])
                except Exception as e:
                    provider.failure(source,code,'probe',e)
                    item.update(available=False,error=provider.attempts[-1]['error'])
                report['sources'].append(item)
    report['attempts']=provider.attempts; report['calendar_status']=provider.calendar_status
    return report

def main():
    parser=argparse.ArgumentParser(description='股票Agent桌面工具')
    parser.add_argument('action',choices=['check','demo','probe','monitor','market-worker','universe'])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--all-sources',action='store_true')
    args=parser.parse_args()
    if args.action=='market-worker':
        from .full_market import main as worker
        from .locking import BusyError
        try: worker()
        except BusyError as e: print(str(e));raise SystemExit(1)
        return
    if args.action=='monitor':
        from .scheduler import main as monitor
        from .locking import BusyError
        try: monitor()
        except BusyError as e:
            print(str(e)); raise SystemExit(1)
        return
    if args.action=='universe':
        from .universe import refresh
        data=refresh(Store('market-real'),load())
        result={k:v for k,v in data.items() if k!='stocks'}|{'count':len(data['stocks'])}
    elif args.action=='check': result=selftest()
    elif args.action=='demo':
        from .engine import scan
        store=Store('demo'); result=scan(Provider(store,load(),True),store,load())
    else: result=probe(all_sources=args.all_sources)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))

if __name__=='__main__': main()
