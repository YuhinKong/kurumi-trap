"""明确构造的模拟执行路径，确保T+1与费用测试确实发生交易。"""
import pandas as pd
import pytest
from monitor.config import DEFAULT
from monitor.backtest import run
from monitor.risk import fee,fill_price

def test_decimal_slippage_and_fee_rounding():
    assert fill_price(5,.001)==5.01
    assert fee(490,DEFAULT,True)==5.25

def test_t_plus_one_and_costs_with_actual_simulated_fill(monkeypatch):
    dates=pd.bdate_range('2026-01-01',periods=60)
    df=pd.DataFrame(dict(date=dates,open=5.,close=5.,high=5.1,low=4.9,volume=100000.,amount=2e7))
    df.loc[36:37,'low']=4.5  # 入场日已触及止损，必须等待下一交易日才可退出
    monkeypatch.setattr('monitor.backtest.evaluate',lambda history,*args:
        {'status':'通过' if history.date.iloc[-1]==dates[35] else '未通过'})
    cfg=DEFAULT|{'min_reward_risk':0}
    result=run(df,dates.date.tolist(),cfg)
    assert len(result['trades'])==1
    trade=result['trades'][0]
    assert trade['entry_date']==str(dates[36].date())
    assert trade['exit_date']==str(dates[37].date())
    expected=490-fee(490,cfg,True)-(501+fee(501,cfg))
    assert trade['profit']==pytest.approx(round(expected,2))
