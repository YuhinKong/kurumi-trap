"""数据质量与时点规则。获取时间永远不能替代供应商行情时间。"""
from datetime import timedelta
import math
import pandas as pd
from .market import TZ, validate

class DataValidator:
    def __init__(self,cfg):
        self.cfg=cfg

    def expected_day(self,at,calendar,include_partial=False):
        if not calendar or max(calendar)<at.date():
            raise ValueError('交易日历未覆盖当前日期')
        minutes=at.hour*60+at.minute
        today_allowed=minutes>=570 if include_partial else minutes>=900+self.cfg['close_delay']
        days=[d for d in calendar if d<at.date() or (d==at.date() and today_allowed)]
        if not days: raise ValueError('交易日历无历史交易日')
        return max(days)

    def history(self,df,code,source,origin,meta,at,calendar,frequency='daily'):
        df=validate(df)
        if 'code' in df and any(str(c).zfill(6)!=code for c in df.code):
            raise ValueError('返回的股票代码与请求不一致')
        # 日线以交易日期校验；分钟线按真实时间校验，禁止未来分钟。
        if (df.date.dt.date>at.date()).any(): raise ValueError('行情包含未来交易日期')
        if any(d not in calendar for d in df.date.dt.date): raise ValueError('行情包含非交易日')
        if frequency!='daily' and (df.date>pd.Timestamp(at.replace(tzinfo=None))).any():
            raise ValueError('行情包含未来分钟')
        complete=[]; times=[]; ages=[]
        for stamp in df.date:
            stamp=stamp.to_pydatetime().replace(tzinfo=TZ)
            if frequency=='daily':
                done=stamp.date()<at.date() or (at.hour*60+at.minute>=900+self.cfg['close_delay'])
                fetched=pd.Timestamp(meta['fetched_at'])
                fetched=fetched.tz_localize(TZ) if fetched.tzinfo is None else fetched.tz_convert(TZ)
                cutoff=stamp.replace(hour=15)+timedelta(minutes=self.cfg['close_delay'])
                if done and fetched.to_pydatetime()<cutoff: done=False
                # 日期粒度的盘中日K无法断定最后更新时间，明确未知。
                bt=stamp.replace(hour=15) if done else None
            else:
                bt=stamp; done=(at-bt).total_seconds()>=300
            complete.append(done); times.append(bt.isoformat() if bt else stamp.date().isoformat())
            ages.append(max(0,(at-bt).total_seconds()) if bt else None)
        df['code']=code; df['source']=source; df['origin']=origin
        from .config import NAMES
        if 'name' not in df: df['name']=NAMES.get(code,'名称未知')
        df['latest_price']=df.close
        df['bar_time']=times; df['fetched_at']=meta['fetched_at']; df['timezone']='Asia/Shanghai'
        df['is_intraday']=[not x for x in complete]; df['is_complete']=complete
        df['data_age_seconds']=ages; df['from_cache']=meta['from_cache']
        expected=self.expected_day(at,calendar,include_partial=True)
        stale=df.date.iloc[-1].date()!=expected
        if at.hour*60+at.minute>=900+self.cfg['close_delay'] and not complete[-1]: stale=True
        df.attrs.update(source=source,origin=origin,from_cache=meta['from_cache'],fetched_at=meta['fetched_at'],
                        stale=stale,quality='数据过期' if stale else '日期覆盖；盘中新鲜度需快照验证')
        return df

    def quote(self,q,at,calendar):
        q=q.copy()
        for key in ('price','open','high','low','volume'):
            v=q.get(key)
            if v is None or not math.isfinite(float(v)) or (float(v)<0 if key=='volume' else float(v)<=0):
                raise ValueError(f'快照{key}非法')
        if q['high']<max(q['open'],q['price'],q['low']) or q['low']>min(q['open'],q['price'],q['high']):
            raise ValueError('快照OHLC关系非法')
        q['close']=q['price']; q['latest_price']=q['price']; q['timezone']='Asia/Shanghai'
        stamp=q.get('bar_time')
        q['data_age_seconds']=None; q['is_realtime']=False; q['is_complete']=False; q['is_intraday']=True
        if not stamp:
            q['quality']='数据过期'; q['quality_reason']='供应商缺少可验证行情时间'
            return q
        bt=pd.Timestamp(stamp)
        bt=bt.tz_localize(TZ) if bt.tzinfo is None else bt.tz_convert(TZ)
        if bt.to_pydatetime()>at: raise ValueError('快照含未来时间')
        if bt.date() not in calendar: raise ValueError('快照日期不在交易日历')
        age=max(0,(at-bt.to_pydatetime()).total_seconds())
        q['bar_time']=bt.isoformat(); q['data_age_seconds']=round(age,1)
        m=at.hour*60+at.minute
        active=at.date() in calendar and (570<=m<=690 or 780<=m<900)
        # 午休允许最后11:30的快照；收盘必须覆盖15:00，不能拿14:59的预收盘价格确认。
        expected=self.expected_day(at,calendar,include_partial=True)
        if active:
            fresh=bt.date()==at.date() and age<=self.cfg['quote_max_age']
        elif at.date() in calendar and 690<m<780:
            fresh=bt.date()==at.date() and 687<=bt.hour*60+bt.minute<=690
        else:
            fresh=bt.date()==expected and bt.hour*60+bt.minute>=900
        q['is_realtime']=bool(active and fresh and not q['from_cache'])
        q['is_intraday']=not (bt.date()<at.date() or bt.hour*60+bt.minute>=900)
        q['is_complete']=not q['is_intraday']
        q['quality']='有效缓存快照' if fresh and q['from_cache'] else '有效行情' if fresh else '数据过期'
        q['fresh']=bool(fresh)
        return q

    def cross(self,a,b):
        result=dict(passed=False,status='数据不足',difference=None,quotes=[a,b])
        if not a or not b or not a.get('fresh') or not b.get('fresh'):
            result['reason']='至少一个来源缺失或行情已过期'; return result
        # 接口独立不足以证明数据源独立：比较真实上游身份。
        if a['origin'] in ('unknown','demo') or a['origin']==b['origin'] or b['origin']=='unknown':
            result['reason']='不足两个已知独立上游'; return result
        if a['code']!=b['code']: result['status']='数据源不一致'; return result
        gap=abs((pd.Timestamp(a['bar_time'])-pd.Timestamp(b['bar_time'])).total_seconds())
        if gap>self.cfg['cross_max_time_gap']:
            result['reason']='行情时间不同步，无法比较'; return result
        difference=abs(a['price']-b['price'])/min(a['price'],b['price'])
        result.update(difference=difference,passed=difference<=self.cfg['cross_tolerance'],
                      status='通过' if difference<=self.cfg['cross_tolerance'] else '数据源不一致')
        result['reason']='独立来源价格和时间均在阈值内' if result['passed'] else '独立来源价格差异超过阈值'
        return result
