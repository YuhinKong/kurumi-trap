from datetime import datetime,date
import pandas as pd
import pytest
from monitor.config import DEFAULT
from monitor.market import Provider,TZ,validate,complete_daily,weekly
from monitor.store import Store
from monitor.strategy import evaluate,indicators
from monitor.risk import assess,fee,tick
from monitor.scheduler import due
from monitor.backtest import run

@pytest.fixture
def bars(tmp_path):
    return Provider(Store('demo',tmp_path/'x.db'),DEFAULT,True).daily('601728',datetime(2026,10,23,16,tzinfo=TZ))

def test_insufficient(bars):
    assert evaluate(bars.head(10),bars.head(5),DEFAULT)['status']=='数据不足'

def test_invalid(bars):
    bars.loc[0,'high']=0
    with pytest.raises(ValueError): validate(bars)

def test_intraday_no_future(bars):
    at=datetime(2026,10,23,14,tzinfo=TZ); cal=pd.bdate_range('2025-01-01','2027-01-01').date.tolist()
    d=complete_daily(bars,at,cal)
    assert d.date.iloc[-1].date()<at.date()
    w=weekly(d,at,cal)
    assert w.date.iloc[-1].date()<=date(2026,10,16)

def test_holiday_week(bars):
    cal=pd.bdate_range('2025-01-01','2027-01-01').date.tolist()
    cal.remove(date(2026,10,23))
    d=bars[bars.date.dt.date<date(2026,10,23)]
    assert weekly(d,datetime(2026,10,23,16,tzinfo=TZ),cal).date.iloc[-1].date()==date(2026,10,22)

def test_affordability():
    assert assess(10,9,DEFAULT)['shares']==0
    r=assess(5,4.8,DEFAULT,amount=2e7,change=0,metadata_known=True)
    assert r['shares']==100 and r['estimated_loss']<=50
    assert fee(500,DEFAULT)==5 and fee(500,DEFAULT,True)==5.25
    assert tick(1.005)==1.01

def test_unknown_risk():
    assert not assess(5,4.8,DEFAULT,amount=2e7,change=0)['eligible']

def test_scheduler():
    cal=[date(2026,10,23)]
    for h,m in [(12,0),(15,5),(9,0)]: assert due(datetime(2026,10,23,h,m,tzinfo=TZ),cal,20) is None
    assert due(datetime(2026,10,23,13,0,tzinfo=TZ),cal,20)
    assert due(datetime(2026,10,24,10,tzinfo=TZ),cal,20) is None

def test_ma_prefix_no_leak(bars):
    assert indicators(bars).MA20.iloc[100]==indicators(bars.iloc[:101]).MA20.iloc[-1]

def test_strategy_positive():
    d=pd.DataFrame({'close':[5+i*.03 for i in range(180)]})
    d['open']=d.close*.999; d['high']=d.close*1.001; d['low']=d.close*.998; d['volume']=100.
    d.loc[179,'volume']=200
    assert evaluate(d,d,DEFAULT)['status']=='通过'
    d.loc[179,'close']=1
    assert evaluate(d,d,DEFAULT)['status']=='未通过'

def test_backtest_prefix(bars):
    cal=pd.bdate_range('2020-01-01','2028-01-01').date.tolist()
    a=run(bars.iloc[:180],cal,DEFAULT); b=run(bars,cal,DEFAULT)
    assert a['equity']==b['equity'][:len(a['equity'])]
    for t in b['trades']: assert t['entry_date']<t['exit_date']

def test_store(tmp_path):
    s=Store(path=tmp_path/'t.db'); s.put('a',[1]); assert s.get('a')[1]==[1]
    assert not s.claimed('x'); s.mark('x'); assert s.claimed('x')
