import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = dict(watchlist=['601728','601668','000498','002376','600050','600004'],
    capital=1000., risk=50., commission=0.0003, minimum_commission=5., tax=0.0005,
    other_fee=0., slippage=0.001, breakout_volume=1.5, pullback_volume=1.1,
    pullback_tolerance=0.02, min_amount=10000000., reward_multiple=2.,
    close_delay=20, request_timeout=12, request_gap=1., retries=2,
    min_reward_risk=1.5, cross_tolerance=0.003, cross_max_time_gap=120,
    quote_max_age=180, quote_cache_seconds=15, history_cache_seconds=120,
    pullback_ma=[5,10], stop_lookback=10, calendar_cache_days=7, clock_wait_seconds=10,
    market_batch_size=10, market_batch_seconds=120, market_interval=10)

NAMES = {'601728':'中国电信','601668':'中国建筑','000498':'山东路桥',
         '002376':'新北洋','600050':'中国联通','600004':'白云机场'}

def validate_config(c):
    import math
    from .sources import symbol
    if not isinstance(c.get('watchlist'),list) or not 1<=len(c['watchlist'])<=100:
        raise ValueError('自选股需为1–100个股票代码；免费接口请从少量开始')
    for code in c['watchlist']: symbol(code)
    for key in ('capital','risk','commission','minimum_commission','tax','other_fee','slippage','breakout_volume','pullback_volume','pullback_tolerance','min_amount','reward_multiple','min_reward_risk','cross_tolerance','quote_max_age','request_gap'):
        if not isinstance(c[key],(float,int)) or not math.isfinite(c[key]) or c[key]<0:
            raise ValueError(f'参数{key}需为非负有限数字')
    if c['capital']<=0 or c['risk']<=0 or c['risk']>c['capital']:
        raise ValueError('资金和风险预算须为正数，风险预算不能超过总资金')
    if not isinstance(c['cross_max_time_gap'],(int,float)) or not math.isfinite(c['cross_max_time_gap']) or c['cross_max_time_gap']<0:
        raise ValueError('双源时间差上限需为非负有限秒数')
    if c['slippage']>=1 or not 0<c['cross_tolerance']<1 or not 0<c['pullback_tolerance']<1:
        raise ValueError('滑点、双源误差和回踩容差必须使用合理的小数比例')
    for key,low,high in [('retries',1,3),('request_timeout',3,60),('close_delay',1,120),('stop_lookback',2,60),('calendar_cache_days',1,30),('quote_cache_seconds',0,300),('history_cache_seconds',0,3600),('clock_wait_seconds',0,30)]:
        if not isinstance(c[key],int) or not low<=c[key]<=high: raise ValueError(f'{key}需为{low}–{high}整数')
    if not c['pullback_ma'] or any(n not in (5,10) for n in c['pullback_ma']):
        raise ValueError('回踩均线仅支持MA5和MA10')
    for key,low,high in [('market_batch_size',1,50),('market_batch_seconds',10,600),('market_interval',1,300)]:
        if not isinstance(c[key],int) or not low<=c[key]<=high: raise ValueError(f'{key}需为{low}–{high}整数')
    c['watchlist']=list(dict.fromkeys(c['watchlist']))
    return c

def load():
    p = ROOT / 'config.json'
    try:
        c=DEFAULT | (json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else {})
        return validate_config(c)
    except (ValueError,TypeError,KeyError) as e:
        raise ValueError('配置错误：'+str(e)) from e

def save(c):
    c=validate_config(c.copy())
    p=ROOT/'config.json'; temporary=p.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(c, ensure_ascii=False, indent=2),encoding='utf-8')
    temporary.replace(p)
