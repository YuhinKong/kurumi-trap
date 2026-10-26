from datetime import datetime
import pandas as pd
from monitor.config import DEFAULT
from monitor.store import Store
from monitor.market import Provider,TZ
from monitor.engine import scan
from monitor.strategy import evaluate

def test_stale_close_not_confirmed(tmp_path):
    s=Store('demo',tmp_path/'db')
    p=Provider(s,DEFAULT,True)
    at=datetime(2026,10,23,16,tzinfo=TZ)
    bars=p.daily('601728',at).iloc[:-1]
    p.daily=lambda code,at:bars
    rows=scan(p,s,DEFAULT|{'watchlist':['601728']},at)
    assert all(r['confirmation']=='未确认' for r in rows)

def test_calendar_expired(tmp_path):
    s=Store(path=tmp_path/'db'); p=Provider(s,DEFAULT,True)
    p.calendar=lambda:[datetime(2025,1,1).date()]
    rows=scan(p,s,DEFAULT,datetime(2026,10,23,16,tzinfo=TZ))
    assert all(r['status']=='数据错误' for r in rows)

def test_pullback_and_bad_data():
    d=pd.DataFrame({'close':[5+i*.03 for i in range(180)]})
    d['open']=d.close*.999; d['high']=d.close*1.001; d['low']=d.close*.998; d['volume']=100.
    d.loc[179,'low']=d.close.tail(10).mean()
    assert evaluate(d,d,DEFAULT,'回踩')['status']=='通过'
    d.loc[179,'volume']=float('nan')
    assert evaluate(d,d,DEFAULT,'回踩')['status']=='数据错误'
