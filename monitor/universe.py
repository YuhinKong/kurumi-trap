"""交易所股票名录。名录只表示代码范围，不作为实时行情或上市状态保证。"""
from .market import AKTransport,now
from .sources import symbol

SPECS=[('沪市主板','stock_info_sh_name_code',{'symbol':'主板A股'},'证券代码','证券简称','sh'),
       ('科创板','stock_info_sh_name_code',{'symbol':'科创板'},'证券代码','证券简称','sh'),
       ('深市含创业板','stock_info_sz_name_code',{'symbol':'A股列表'},'A股代码','A股简称','sz'),
       ('北交所','stock_info_bj_name_code',{},'证券代码','证券简称','bj')]

def normalize(rows,code_key='code',name_key='name',exchange=None):
    result={}
    for row in rows:
        code=str(row[code_key]).strip().zfill(6); name=str(row[name_key]).strip()
        actual=symbol(code)[:2]
        if exchange and actual!=exchange: raise ValueError('名录代码与交易所不符：'+code)
        if not name or name.lower() in ('nan','none'): raise ValueError('名录缺少股票名称')
        result[code]=dict(code=code,name=name,exchange=actual)
    if not result: raise ValueError('股票名录为空')
    return sorted(result.values(),key=lambda r:r['code'])

def refresh(store,cfg,demo=False):
    if demo:
        from .config import NAMES
        result=dict(time=now().isoformat(),source='模拟名录（非全市场）',complete=False,demo=True,
                    stocks=normalize([dict(code=c,name=n) for c,n in NAMES.items()]),segments=[])
    else:
        transport=AKTransport(store,cfg|{'retries':1,'request_timeout':30})
        stocks=[]; segments=[]
        for label,api,kwargs,ck,nk,exchange in SPECS:
            try:
                rows=transport.request(api,kwargs,ttl=86400)
                values=normalize(rows,ck,nk,exchange)
                stocks.extend(values)
                segments.append(dict(segment=label,ok=True,count=len(values),**transport.response_meta))
            except Exception as e:
                segments.append(dict(segment=label,ok=False,count=0,error=str(e)))
                store.event('log',dict(kind='universe_error',segment=label,error=str(e)))
        if not stocks: raise RuntimeError('四个名录接口全部失败；旧名录未被覆盖，请查看日志或稍后重试')
        result=dict(time=now().isoformat(),source='AKShare/沪深京交易所名录',complete=all(s['ok'] for s in segments),
                    demo=False,stocks=normalize(stocks),segments=segments)
    store.put('market:universe',result)
    return result
