"""小型来源适配器：禁止把网络失败转成虚构行情。所有价格使用不复权口径。"""
import json
import os
import re
import time
from datetime import timedelta
from urllib.parse import urlsplit
import pandas as pd
import requests
from .market import AKTransport,now

def symbol(code):
    if not isinstance(code,str) or len(code)!=6 or not code.isdigit(): raise ValueError('股票代码必须为6位字符串')
    if not code.startswith(('60','68','00','30','8','4','92')):
        raise ValueError('本版仅支持A股股票，不支持ETF、基金或指数代码')
    return ('sh' if code.startswith('6') else 'bj' if code.startswith(('4','8','92')) else 'sz')+code

class HTTPClient:
    def __init__(self,store,cfg):
        self.store,self.cfg=store,cfg
        self.session=requests.Session()
        # 仅作用于本客户端；不修改操作系统或全局代理。默认尊重用户代理。
        self.session.trust_env=os.getenv('MARKET_TRUST_ENV','1')!='0'
        self.last=0

    def get(self,key,url,params=None,ttl=0,encoding=None,headers=None):
        old=self.store.get('v2:'+key)
        if old and time.time()-old[0]<ttl:
            return old[1],dict(from_cache=True,fetched_at=pd.Timestamp(old[0],unit='s',tz='Asia/Shanghai').isoformat())
        for attempt in range(min(3,max(1,self.cfg['retries']))):
            time.sleep(max(0,self.cfg['request_gap']-(time.monotonic()-self.last)))
            self.last=time.monotonic()
            try:
                # 本机地址不应经由外网代理；其他行情连接继续遵守用户代理设置。
                local=urlsplit(url).hostname in ('127.0.0.1','localhost','::1')
                options={'proxies':{'http':'','https':''}} if local else {}
                r=self.session.get(url,params=params,timeout=(3,self.cfg['request_timeout']),headers=headers,**options)
                r.raise_for_status()
                if encoding: r.encoding=encoding
                text=r.text
                if not text.strip(): raise ValueError('接口返回空响应')
                self.store.put('v2:'+key,text)
                return text,dict(from_cache=False,fetched_at=now().isoformat())
            except Exception:
                if attempt+1>=min(3,max(1,self.cfg['retries'])): raise
                time.sleep(attempt+1)

class AKShareSource:
    name='AKShare / 东方财富'; origin='eastmoney'
    def __init__(self,transport): self.transport=transport; self.spot_failed=False
    def daily(self,code,at):
        df=self.transport.daily(code,at)
        return df,self.transport.response_meta.copy()
    def quote(self,code,at):
        if self.spot_failed: raise RuntimeError('本轮批量快照接口已失败，直接使用备用源')
        try: q=self.transport.spot().get(code)
        except Exception:
            self.spot_failed=True
            raise
        if not q: raise ValueError('快照无此股票')
        # 东方财富批量快照没有逐笔时间，保留None，验证器不得赋值为请求时间。
        return dict(code=code,name=q['名称'],price=q['最新价'],open=q['今开'],high=q['最高'],low=q['最低'],
                    volume=q['成交量'],amount=q['成交额'],change=q['涨跌幅'],bar_time=None),self.transport.response_meta.copy()



class TencentSource:
    name='腾讯公开行情'; origin='tencent'
    def __init__(self,http,cfg): self.http,self.cfg=http,cfg
    def daily(self,code,at):
        sym=symbol(code)
        text,meta=self.http.get(f'tencent:daily:{code}:{at.date()}',
            'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
            params={'param':f'{sym},day,,{at:%Y-%m-%d},640,'},ttl=self.cfg['history_cache_seconds'])
        payload=json.loads(text)
        if payload.get('code')!=0: raise ValueError('腾讯日K服务返回错误')
        rows=payload.get('data',{}).get(sym,{}).get('day',[])
        if not rows: raise ValueError('腾讯未返回不复权day字段')
        df=pd.DataFrame([r[:6] for r in rows],columns=['date','open','close','high','low','volume'])
        # 此接口不提供历史成交额，禁止以成交量×价格替代真实值。
        df['amount']=float('nan')
        return df,meta
    def quote(self,code,at):
        text,meta=self.http.get(f'tencent:quote:{code}','https://qt.gtimg.cn/q='+symbol(code),
            ttl=self.cfg['quote_cache_seconds'],encoding='gbk')
        match=re.search(r'="(.*?)";',text,re.S)
        if not match: raise ValueError('腾讯快照格式错误')
        f=match[1].split('~')
        if len(f)<39 or f[2]!=code: raise ValueError('腾讯代码或字段不匹配')
        return dict(code=f[2],name=f[1],price=float(f[3]),open=float(f[5]),high=float(f[33]),low=float(f[34]),
                    volume=float(f[6]),amount=float(f[37])*10000,change=float(f[32]),
                    bar_time=pd.to_datetime(f[30],format='%Y%m%d%H%M%S').isoformat()),meta

class SinaSource:
    """新浪日K备用适配器，以及与腾讯独立交叉验证的快照。"""
    name='新浪公开行情'; origin='sina'
    def __init__(self,http,cfg,transport=None): self.http,self.cfg,self.transport=http,cfg,transport
    def daily(self,code,at):
        if self.transport is None: raise RuntimeError('新浪历史适配器未配置传输层')
        rows=self.transport.request('stock_zh_a_daily',dict(symbol=symbol(code),start_date=(at-timedelta(days=1000)).strftime('%Y%m%d'),end_date=at.strftime('%Y%m%d'),adjust=''),ttl=self.cfg['history_cache_seconds'])
        df=pd.DataFrame(rows)
        if 'amount' not in df: df['amount']=float('nan')
        df['volume']=pd.to_numeric(df.volume)/100
        return df,self.transport.response_meta.copy()
    def quote(self,code,at):
        text,meta=self.http.get(f'sina:quote:{code}','https://hq.sinajs.cn/list='+symbol(code),
            ttl=self.cfg['quote_cache_seconds'],encoding='gbk',headers={'Referer':'https://finance.sina.com.cn/'})
        match=re.search(r'hq_str_'+re.escape(symbol(code))+r'="(.*?)";',text,re.S)
        if not match: raise ValueError('新浪快照格式错误')
        f=match[1].split(',')
        if len(f)<32: raise ValueError('新浪快照字段不足')
        return dict(code=code,name=f[0],price=float(f[3]),open=float(f[1]),high=float(f[4]),low=float(f[5]),
                    volume=float(f[8])/100,amount=float(f[9]),change=(float(f[3])/float(f[2])-1)*100,
                    bar_time=f'{f[30]}T{f[31]}'),meta
