import numpy as np

def indicators(df):
    df=df.copy()
    for n in (5,10,20,30): df[f'MA{n}']=df.close.rolling(n).mean()
    return df

def evaluate(daily,week,cfg,kind='突破'):
    if len(daily)<31 or len(week)<30:
        return dict(status='数据不足',reasons=['需要至少31根日K和30根完整周K'])
    if not np.isfinite(daily[['open','high','low','close','volume']].to_numpy()).all() or not np.isfinite(week[['close','volume']].to_numpy()).all():
        return dict(status='数据错误',reasons=['价格或成交量非法'])
    d,w=indicators(daily),indicators(week)
    x,y=d.iloc[-1],w.iloc[-1]
    base=daily.volume.iloc[-6:-1].mean()
    if base<=0: return dict(status='数据不足',reasons=['过去5日成交量为零'])
    ratio=float(x.volume/base)
    checks={'日均线多头':x.MA5>x.MA10>x.MA20>x.MA30,'价格高于MA5':x.close>x.MA5,
            '完整周线多头':y.MA5>y.MA10>y.MA20>y.MA30 and y.close>y.MA5}
    if kind=='突破':
        checks.update({'突破前20日最高价':x.close>d.high.iloc[-21:-1].max(),'放量':ratio>=cfg['breakout_volume']})
    else:
        touched=any(abs(x.low/x[f'MA{n}']-1)<=cfg['pullback_tolerance'] for n in cfg.get('pullback_ma',[5,10]))
        checks.update({'触及MA5/MA10附近':touched,
            '收阳企稳':x.close>=x.open and x.close>=d.close.iloc[-2], '回踩量未放大':ratio<=cfg['pullback_volume']})
    return dict(status='通过' if all(checks.values()) else '未通过',reasons=[f'{k}：{"满足" if v else "不满足"}' for k,v in checks.items()],volume_ratio=round(ratio,3),
                checks={k:bool(v) for k,v in checks.items()},daily_trend=bool(checks['日均线多头']),weekly_trend=bool(checks['完整周线多头']),
                calculations=dict(daily_ma={str(n):float(x[f'MA{n}']) for n in (5,10,20,30)},
                    weekly_ma={str(n):float(y[f'MA{n}']) for n in (5,10,20,30)},
                    previous_20_high=float(d.high.iloc[-21:-1].max()),previous_5_volume=float(base),close=float(x.close)))
