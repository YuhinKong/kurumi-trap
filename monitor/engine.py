"""扫描隔离单股错误；规则通过、数据确认、风险优先级分别判断。"""
import math
from .config import DEFAULT,NAMES
from .market import now,complete_daily,weekly
from .strategy import evaluate
from .risk import assess
from .notify import notify

def _scan(provider,store,cfg,at=None,preselect=False):
    explicit_at=at
    at=at or now(); cfg=DEFAULT|cfg; results=[]
    try:
        calendar=provider.calendar()
        if not calendar or max(calendar)<at.date(): raise ValueError('交易日历未覆盖当前日期，禁止猜测交易日')
    except Exception as e:
        rows=[dict(version='v01-enhanced-1',code=c,name=NAMES.get(c,''),status='数据错误',final_status='数据错误',confirmation='未确认',error=str(e)) for c in cfg['watchlist']]
        store.event('scan',rows); return rows
    for code in cfg['watchlist']:
        try:
            raw=provider.daily(code,at)
            if (raw.date.dt.date>at.date()).any(): raise ValueError('接口包含未来日期')
            daily=complete_daily(raw,at,calendar,cfg['close_delay'])
            week=weekly(daily,at,calendar)
            ready=at.hour*60+at.minute>=900+cfg['close_delay']
            intraday=at.date() in calendar and 570<=at.hour*60+at.minute and not ready
            expected=provider.validator.expected_day(at,calendar,include_partial=intraday)
            fresh=raw.date.iloc[-1].date()==expected and not raw.attrs.get('stale',False)
            use=raw if intraday else daily
            if use.empty: raise ValueError('无可用日K')
            signals={k:evaluate(use,week,cfg,k) for k in ('突破','回踩')}
            preliminary=preselect and not any(s['status']=='通过' for s in signals.values())
            q=None if preliminary else provider.quote(code,explicit_at)
            cross=dict(passed=False,status='数据不足',reason='策略未通过，无需交叉验证')
            if any(s['status']=='通过' for s in signals.values()):
                cross=provider.cross_validate(code,q,explicit_at)
                if cross.get('quotes'): q=cross['quotes'][0]
            for kind,signal in signals.items():
                confirmation='预警' if intraday and fresh else '确认' if fresh and not intraday else '未确认'
                latest_ok=bool(q and q.get('fresh'))
                final='观察'
                if not fresh: final='数据过期'
                elif not q: final='数据错误'
                elif not latest_ok: final='数据过期'
                elif signal['status'] in ('数据不足','数据错误'): final=signal['status']
                elif signal['status']=='通过':
                    if cross['status']=='数据源不一致': final='数据源不一致'
                    elif not cross['passed']: final='数据不足'
                    else: final='盘中预警' if intraday else '收盘确认'
                if final in ('数据过期','数据源不一致','数据不足','数据错误'): confirmation='未确认'
                if preliminary:
                    final='数据过期' if not fresh else signal['status'] if signal['status'] in ('数据不足','数据错误') else '观察'
                    confirmation='无候选' if final=='观察' else '未确认'
                bar_diff=abs(float(use.close.iloc[-1])-q['price'])/q['price'] if latest_ok else None
                if signal['status']=='通过' and final!='数据源不一致' and bar_diff is not None and bar_diff>cfg['cross_tolerance']:
                    final='数据过期'; confirmation='未确认'
                if signal['status']!='通过' and final=='观察': confirmation='无候选'
                amount=float(use.amount.iloc[-1])
                if not math.isfinite(amount):
                    amount=float(q.get('amount') or 0) if latest_ok and raw.date.iloc[-1].date()==expected else 0
                    if not math.isfinite(amount): amount=0
                risk=assess(float(use.close.iloc[-1]),float(use.low.tail(cfg['stop_lookback']).min()),cfg,
                    name=(q or {}).get('name',NAMES.get(code,'')),amount=amount,change=(q or {}).get('change'),code=code)
                row=dict(version='v01-enhanced-1',code=code,name=(q or {}).get('name',NAMES.get(code,'')),kind=kind,**signal,
                    final_status=final,confirmation=confirmation,source=raw.attrs.get('source','模拟' if provider.demo else '未知'),
                    quote_source=(q or {}).get('source','不可用'),price=(q or {}).get('price'),
                    timezone='Asia/Shanghai',bar_time=(q or {}).get('bar_time'),daily_bar_time=str(raw.date.iloc[-1]),
                    fetched_at=(q or {}).get('fetched_at',raw.attrs.get('fetched_at')),from_cache=(q or {}).get('from_cache',False),
                    data_age_seconds=(q or {}).get('data_age_seconds'),is_realtime=(q or {}).get('is_realtime',False),
                    quality=(q or {}).get('quality','日K初筛（非实时）' if preliminary else '模拟行情' if provider.demo else '快照不可用'),
                    preliminary=preliminary,
                    daily_complete=not intraday,weekly='仅使用完整周线',risk=risk,cross=cross,
                    quote=q,bar_quote_difference=bar_diff,priority_candidate=bool(final in ('盘中预警','收盘确认') and risk['eligible']),
                    budget_pass=risk.get('budget_pass',False),
                    calendar_status=provider.calendar_status,
                    diagnostics=[x.copy() for x in provider.attempts if x.get('code')==code],
                    close_ready=bool(not intraday and fresh and latest_ok and (signal['status']!='通过' or cross.get('passed'))),
                    daily_last=use[['date','open','high','low','close','volume']].tail(1).to_dict('records')[0])
                results.append(row)
                if final in ('盘中预警','收盘确认') and not provider.demo:
                    key=f'v01e:{code}:{kind}:{expected}:{confirmation}'
                    store.record_signal(key,row)
                    if cfg.get('notify_enabled',True):
                        notify(store,key,f'{code} {kind} {confirmation}；仅规则候选，非买入指令，需人工核验风险',False)
        except Exception as e:
            results.append(dict(version='v01-enhanced-1',code=code,name=NAMES.get(code,''),status='数据错误',final_status='数据错误',confirmation='未确认',error=str(e),diagnostics=[x.copy() for x in provider.attempts if x.get('code')==code]))
            store.event('log',dict(code=code,error=str(e)))
    store.event('scan',results)
    return results


def scan(provider,store,cfg,at=None,preselect=False):
    from .locking import ProcessLock
    with ProcessLock(store.path.with_suffix('.scan.lock')):
        return _scan(provider,store,cfg,at,preselect)
