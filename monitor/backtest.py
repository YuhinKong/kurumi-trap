"""逐日向前回放；收盘信号下一交易日开盘成交，禁止当日卖出。"""
import pandas as pd
from .market import weekly,TZ
from .strategy import evaluate
from .risk import assess,fee,tick,fill_price

def run(df,calendar,cfg,kind='突破'):
    cash=cfg['capital']; position=None; trades=[]; curve=[]
    pending=None
    for i in range(1,len(df)):
        bar=df.iloc[i]; day=bar.date.date()
        previous=float(df.close.iloc[i-1])
        # 保守模拟主板10%限制；未知特殊板块不适用本研究模型
        buy_block=bar.open>=tick(previous*1.1) or bar.volume<=0
        sell_block=bar.open<=tick(previous*.9) or bar.volume<=0
        if position and day>position['day']:
            if (bar.low<=position['stop'] or bar.high>=position['target']) and not sell_block:
                # 同日同时触及，优先按失效处理；跳空按更差开盘价
                px=min(bar.open,position['stop']) if bar.low<=position['stop'] else position['target']
                px=fill_price(px,cfg['slippage'],False); value=px*position['q']
                cash+=value-fee(value,cfg,True)
                trades.append(dict(entry_date=str(position['day']),exit_date=str(day),profit=round(value-fee(value,cfg,True)-position['cost'],2)))
                position=None
        if pending and not position and not buy_block:
            local=cfg|{'capital':cash}
            r=assess(float(bar.open),pending,local,amount=float(df.amount.iloc[i-1]),change=0,metadata_known=True)
            if r['eligible'] and r['shares']:
                q=r['shares']; cost=q*r['entry']+fee(q*r['entry'],cfg)
                cash-=cost; position=dict(q=q,day=day,stop=r['stop'],target=r['target'],cost=cost)
        pending=None
        history=df.iloc[:i+1].copy()
        at=pd.Timestamp(bar.date).to_pydatetime().replace(hour=16,tzinfo=TZ)
        if not position and evaluate(history,weekly(history,at,calendar),cfg,kind)['status']=='通过':
            pending=float(history.low.tail(cfg.get('stop_lookback',10)).min())
        curve.append(dict(date=str(day),equity=cash+(position['q']*bar.close if position else 0)))
    return dict(trades=trades,equity=curve,open_position=position,
        assumptions='仅普通主板历史研究；无复权数据受除权影响；缺失历史成交额会保守阻止入场；未建模盘口排队、历史ST变更和财报，不能视为可实现收益。持仓期末按市值计价，未强制平仓。')
