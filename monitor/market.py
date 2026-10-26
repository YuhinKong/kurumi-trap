import json, subprocess, sys, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from .config import ROOT

TZ = ZoneInfo('Asia/Shanghai')
def now():
    return datetime.now(TZ)

def validate(df):
    required = ['date','open','high','low','close','volume','amount']
    if df.empty or not set(required).issubset(df):
        raise ValueError('行情为空或字段缺失')
    df = df.copy()
    dates=pd.to_datetime(df.date,errors='coerce')
    df['date']=dates.dt.tz_convert(TZ).dt.tz_localize(None) if dates.dt.tz is not None else dates
    for k in required[1:]:
        df[k] = pd.to_numeric(df[k],errors='coerce')
    # 某些公开K线接口不提供成交额。保留缺失值，禁止用价格乘成交量伪造。
    if not np.isfinite(df[['open','high','low','close','volume']].to_numpy()).all():
        raise ValueError('行情含空值或非有限数字')
    if df.amount.dropna().map(lambda v: not np.isfinite(v)).any():
        raise ValueError('成交额含非法值')
    if df.date.isna().any() or df.date.duplicated().any() or (df[['open','high','low','close']]<=0).any().any() or (df[['volume','amount']]<0).any().any():
        raise ValueError('行情存在重复时间、非法价格或负成交量')
    if ((df.high < df[['open','close','low']].max(axis=1)) | (df.low > df[['open','close','high']].min(axis=1))).any():
        raise ValueError('OHLC价格关系错误')
    return df.sort_values('date').reset_index(drop=True)

class AKTransport:
    def __init__(self,store,cfg,demo=False):
        self.store,self.cfg,self.demo = store,cfg,demo
        self.last = 0.
    def request(self,name,kwargs=None,ttl=60):
        kwargs = kwargs or {}
        key = name+json.dumps(kwargs,sort_keys=True)
        old = self.store.get(key)
        if old and time.time()-old[0]<ttl:
            self.response_meta=dict(fetched_at=datetime.fromtimestamp(old[0],TZ).isoformat(),from_cache=True)
            return old[1]
        error = ''
        for attempt in range(min(3,max(1,self.cfg['retries']))):
            time.sleep(max(0,self.cfg['request_gap']-(time.monotonic()-self.last)))
            self.last=time.monotonic()
            try:
                import os
                env=os.environ.copy(); env['PYTHONUTF8']='1'
                if env.get('MARKET_TRUST_ENV','1')=='0':
                    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'): env.pop(key,None)
                p=subprocess.run([sys.executable,'-m','monitor.worker',json.dumps([name,kwargs])],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=self.cfg['request_timeout'],env=env)
                if p.returncode:
                    fault=next((label for label in ('ProxyError','RemoteDisconnected','Max retries exceeded','ConnectionError','ValueError','KeyError') if label in p.stderr),'接口子进程失败')
                    raise RuntimeError(fault+'；详查供应商连接及接口字段')
                data=json.loads(p.stdout.split('RESULT_JSON:')[-1])
                if not data: raise ValueError('接口返回空数据')
                self.store.put(key,data)
                self.response_meta=dict(fetched_at=now().isoformat(),from_cache=False)
                return data
            except Exception as e:
                error=str(e)
                self.store.event('log',dict(interface=name,error=error,attempt=attempt+1))
                time.sleep(attempt+1)
        # 失败不静默返回旧行情，以免误认实时数据
        raise RuntimeError(f'{name}失败（{self.cfg["retries"]}次）：{error}')
    def calendar(self):
        if self.demo:
            return pd.bdate_range('2020-01-01','2030-12-31').date.tolist()
        rows=self.request('tool_trade_date_hist_sina',ttl=86400)
        return sorted(pd.to_datetime([r['trade_date'] for r in rows]).date)
    def daily(self,code,at=None):
        at=at or now()
        if self.demo:
            dates=pd.bdate_range(end=at.date(),periods=260)
            rng=np.random.default_rng(int(code))
            prices=5*np.exp(np.cumsum(rng.normal(.001,.012,len(dates))))
            df=pd.DataFrame(dict(date=dates,open=prices*.997,close=prices,high=prices*1.015,low=prices*.98,volume=rng.integers(100000,500000,len(dates))))
            df['amount']=df.volume*100*df.close
            return validate(df)
        rows=self.request('stock_zh_a_hist',dict(symbol=code,period='daily',start_date=(at-timedelta(days=800)).strftime('%Y%m%d'),end_date=at.strftime('%Y%m%d'),adjust=''),ttl=self.cfg['history_cache_seconds'])
        return validate(pd.DataFrame(rows).rename(columns={'日期':'date','开盘':'open','最高':'high','最低':'low','收盘':'close','成交量':'volume','成交额':'amount'}))
    def minutes(self,code):
        rows=self.request('stock_zh_a_hist_min_em',dict(symbol=code,period='5',adjust=''),ttl=240)
        return validate(pd.DataFrame(rows).rename(columns={'时间':'date','开盘':'open','最高':'high','最低':'low','收盘':'close','成交量':'volume','成交额':'amount'}))
    def spot(self):
        if self.demo: return {}
        rows=self.request('stock_zh_a_spot_em',ttl=240)
        return {str(r['代码']).zfill(6):r for r in rows}

def complete_daily(df,at,calendar,delay=20):
    """仅在交易日收盘并留出更新窗口后将该日K视为完整。"""
    cutoff=at.replace(hour=15,minute=0,second=0,microsecond=0)+timedelta(minutes=delay)
    return df[(df.date.dt.date<at.date()) | ((df.date.dt.date==at.date()) & (at>=cutoff) & (at.date() in calendar))].copy()

def weekly(df,at,calendar):
    """按已知交易日历判断本周最后交易日，避免直接用未完成周K。"""
    groups=[]
    for _,g in df.groupby(df.date.dt.to_period('W-FRI')):
        end=g.date.iloc[-1].date()
        monday=end-timedelta(days=end.weekday())
        friday=monday+timedelta(days=4)
        if not calendar or max(calendar)<friday: continue
        days=[d for d in calendar if monday<=d<=friday]
        if not days or end!=max(days) or end>at.date(): continue
        # 首段若从周中才开始，不能把这段截断历史当作完整周线。
        if g.index.min()==df.index.min() and g.date.iloc[0].date()>min(days): continue
        groups.append(dict(date=g.date.iloc[-1],open=g.open.iloc[0],high=g.high.max(),low=g.low.min(),close=g.close.iloc[-1],volume=g.volume.sum(),amount=g.amount.sum(min_count=1)))
    return pd.DataFrame(groups,columns=['date','open','high','low','close','volume','amount'])

def Provider(store,cfg,demo=False):
    """兼容V0.1入口；数据层实现已迁移为可组合的DataProvider。"""
    from .data_provider import DataProvider
    return DataProvider(store,cfg,demo)
