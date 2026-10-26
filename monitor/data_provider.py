"""行情编排：日K多源回退，快照有时间戳，候选必须独立双源校验。"""
from datetime import datetime
import time
import pandas as pd
from .config import DEFAULT,NAMES
from .market import AKTransport,now,complete_daily,weekly
from .sources import HTTPClient,AKShareSource,TencentSource,SinaSource,symbol
from .validator import DataValidator

class DataProvider:
    def __init__(self,store,cfg,demo=False,sources=None,quote_sources=None):
        self.store,self.cfg,self.demo=store,DEFAULT|cfg,demo
        self.transport=AKTransport(store,self.cfg,demo)
        http=HTTPClient(store,self.cfg)
        tencent=TencentSource(http,self.cfg)
        sina=SinaSource(http,self.cfg,self.transport)
        self.sources=sources if sources is not None else [AKShareSource(self.transport),tencent,sina]
        # 不抓全市场大快照：逐股腾讯/新浪提供可验证的供应商时间。
        self.quote_sources=quote_sources if quote_sources is not None else [tencent,sina]
        self.validator=DataValidator(self.cfg)
        self.attempts=[]; self._calendar=None; self._quotes={}
        self.calendar_status='尚未读取交易日历'

    def calendar(self):
        if self._calendar is not None: return self._calendar
        if self.demo:
            self._calendar=self.transport.calendar(); self.calendar_status='模拟工作日日历（不代表实际交易日）'
            return self._calendar
        try:
            days=self.transport.calendar()
            if not days or max(days)<now().date(): raise ValueError('交易日历未覆盖当前日期')
            self.calendar_status='日历缓存' if getattr(self.transport,'response_meta',{}).get('from_cache') else '已刷新交易日历'
            self._calendar=days
        except Exception:
            cached=self.store.get('tool_trade_date_hist_sina{}')
            if not cached or time.time()-cached[0]>self.cfg['calendar_cache_days']*86400: raise
            days=sorted(pd.to_datetime([r['trade_date'] for r in cached[1]]).date)
            if not days or max(days)<now().date(): raise ValueError('缓存交易日历也未覆盖当前日期')
            self._calendar=days
            self.calendar_status='日历刷新失败，使用有覆盖的历史日历缓存（非行情缓存）'
            self.store.event('log',dict(kind='calendar_warning',message=self.calendar_status,cache_time=datetime.fromtimestamp(cached[0]).isoformat()))
        return self._calendar

    def failure(self,source,code,kind,error):
        import re
        text=re.sub(r'https?://\S+','[URL已隐藏]',str(error),flags=re.IGNORECASE)
        item=dict(source=source.name,code=code,kind=kind,error=text[-350:])
        self.attempts.append(item); self.store.event('log',item)

    def daily(self,code,at=None):
        symbol(code); at=at or now(); cal=self.calendar()
        if self.demo:
            frame=self.transport.daily(code,at)
            return self.validator.history(frame,code,'模拟生成（非真实行情）','demo',dict(fetched_at=at.isoformat(),from_cache=False),at,cal)
        insufficient=[]; stale=[]
        for source in self.sources:
            try:
                frame,meta=source.daily(code,at)
                frame=self.validator.history(frame,code,source.name,source.origin,meta,at,cal)
                daily=complete_daily(frame,at,cal,self.cfg['close_delay']); weeks=weekly(daily,at,cal)
                enough=len(daily)>=31 and len(weeks)>=30
                frame.attrs.update(complete_daily_rows=len(daily),complete_weekly_rows=len(weeks),history_sufficient=enough)
                if not frame.attrs['stale'] and enough: return frame
                if frame.attrs['stale']:
                    stale.append(frame); reason='最新交易日未覆盖，继续备用来源'
                else:
                    insufficient.append(frame); reason=f'历史不足：完整日K{len(daily)}根、完整周K{len(weeks)}根，继续备用来源'
                self.failure(source,code,'daily',ValueError(reason))
            except Exception as e: self.failure(source,code,'daily',e)
        if insufficient: return max(insufficient,key=len)
        if stale: return max(stale,key=lambda d:d.date.iloc[-1])
        raise RuntimeError('全部日K来源失败；查看系统状态/日志中的该股票原因')

    def quote_from(self,source,code,at=None):
        key=(source.name,code)
        existing=self._quotes.get(key)
        if existing and time.monotonic()-existing[0]<self.cfg['quote_cache_seconds']:
            q=existing[1].copy(); q['from_cache']=True
        else:
            q,meta=source.quote(code,at or now())
            if q.get('code')!=code: raise ValueError('快照代码与请求不一致')
            q.update(source=source.name,origin=source.origin,**meta)
            if not q.get('name'): q['name']=NAMES.get(code,'名称未知')
            self._quotes[key]=(time.monotonic(),q.copy())
        if at is None and q.get('bar_time'):
            bt=pd.Timestamp(q['bar_time'])
            bt=bt.tz_localize('Asia/Shanghai') if bt.tzinfo is None else bt.tz_convert('Asia/Shanghai')
            ahead=(bt.to_pydatetime()-now()).total_seconds()
            if ahead>self.cfg['clock_wait_seconds']:
                raise ValueError(f'供应商行情时间领先本机{ahead:.1f}秒，超过等待上限；请检查Windows时间同步')
            if ahead>0:
                # 保留原bar_time/fetched_at；等待时间真正到达后才允许进入计算。
                time.sleep(ahead+.05)
                q['clock_note']=f'报价最初领先本机{ahead:.1f}秒，已等待至该时间后复核；建议同步Windows时间'
        verified=self.validator.quote(q,at or now(),self.calendar())
        verified['validated_at']=(at or now()).isoformat()
        return verified

    def quote(self,code,at=None):
        symbol(code)
        if self.demo:
            at=at or now(); df=self.daily(code,at); x=df.iloc[-1]
            stamp=at if x.date.date()==at.date() else x.date.to_pydatetime().replace(hour=15,tzinfo=at.tzinfo)
            q=dict(code=code,name=NAMES.get(code,'模拟股票'),source='模拟行情',origin='demo',price=float(x.close),
                open=float(x.open),high=float(x.high),low=float(x.low),volume=float(x.volume),amount=float(x.amount),
                change=0,bar_time=stamp.isoformat(),fetched_at=at.isoformat(),from_cache=False)
            q=self.validator.quote(q,at,self.calendar()); q.update(quality='模拟行情',is_realtime=False)
            return q
        stale=[]
        for source in self.quote_sources:
            try:
                q=self.quote_from(source,code,at)
                if q.get('fresh'): return q
                stale.append(q)
                self.failure(source,code,'quote',ValueError(q.get('quality_reason','快照已过期：'+str(q.get('bar_time')))))
            except Exception as e: self.failure(source,code,'quote',e)
        return max(stale,key=lambda q:q.get('bar_time') or '') if stale else None

    def cross_validate(self,code,primary,at=None):
        if self.demo: return dict(passed=False,status='数据不足',reason='模拟模式不生成真实候选')
        if not primary: return dict(passed=False,status='数据不足',reason='缺少有效主快照',quotes=[])
        last=None
        for source in self.quote_sources:
            if source.origin==primary['origin']: continue
            try:
                q=self.quote_from(source,code,at)
                a=self.validator.quote(primary,at or now(),self.calendar())
                last=self.validator.cross(a,q)
                if last['passed'] or last['status']=='数据源不一致': return last
            except Exception as e: self.failure(source,code,'cross',e)
        return last or dict(passed=False,status='数据不足',reason='独立且同步的新鲜快照不足两个',quotes=[primary])

    def minutes(self,code):
        symbol(code)
        df=self.transport.minutes(code)
        return self.validator.history(df,code,'AKShare / 东方财富','eastmoney',self.transport.response_meta.copy(),now(),self.calendar(),frequency='5min')

    def spot(self):
        """V0.1兼容入口；新扫描不使用缺时间戳的全市场快照。"""
        return self.transport.spot()
