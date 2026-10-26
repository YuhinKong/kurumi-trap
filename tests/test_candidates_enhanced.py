from datetime import datetime
import pandas as pd
import pytest
from monitor.config import DEFAULT
from monitor.market import TZ,Provider
from monitor.store import Store
from monitor.validator import DataValidator
from monitor.engine import scan

def prepared(tmp_path,at):
    store=Store(path=tmp_path/'db')
    p=Provider(store,DEFAULT,True)
    dates=pd.bdate_range(end=at.date(),periods=180)
    df=pd.DataFrame({'date':dates,'close':[5+i*.03 for i in range(180)]})
    df['open']=df.close*.999; df['high']=df.close*1.001; df['low']=df.close*.998
    df['volume']=100.; df['amount']=2e7; df.loc[179,'volume']=200.
    df.attrs['source']='可控测试日K（模拟）'
    p.daily=lambda code,at:df.copy()
    stamp=at if at.hour<15 else at.replace(hour=15,minute=0)
    price=float(df.close.iloc[-1])
    q=dict(code='601728',name='中国电信',price=price,open=price*.999,high=price*1.001,
           low=price*.998,volume=200,amount=2e7,change=0,source='测试源A',origin='A',
           bar_time=stamp.isoformat(),fetched_at=at.isoformat(),from_cache=False)
    q=p.validator.quote(q,at,p.calendar())
    p.quote=lambda code,at=None:q.copy()
    p.demo=False  # 测试真实确认分支，但所有行情在本测试内明确构造
    return p,store,q

@pytest.mark.parametrize('hour,final,confirmation',[(14,'盘中预警','预警'),(16,'收盘确认','确认')])
def test_complete_bar_and_cross_gates(tmp_path,monkeypatch,hour,final,confirmation):
    at=datetime(2026,10,23,hour,tzinfo=TZ)
    p,s,q=prepared(tmp_path,at)
    p.cross_validate=lambda code,primary,at=None:p.validator.cross(primary,q|{'source':'测试源B','origin':'B'})
    sent=[]; monkeypatch.setattr('monitor.engine.notify',lambda *a:sent.append(a))
    result=scan(p,s,DEFAULT|{'watchlist':['601728']},at)
    breakout=next(r for r in result if r['kind']=='突破')
    assert breakout['status']=='通过'
    assert breakout['final_status']==final and breakout['confirmation']==confirmation
    assert len(sent)==1

def test_inconsistent_sources_block_candidate(tmp_path,monkeypatch):
    at=datetime(2026,10,23,16,tzinfo=TZ); p,s,q=prepared(tmp_path,at)
    p.cross_validate=lambda code,primary,at=None:p.validator.cross(primary,q|{'origin':'B','price':q['price']*1.01})
    sent=[]; monkeypatch.setattr('monitor.engine.notify',lambda *a:sent.append(a))
    row=scan(p,s,DEFAULT|{'watchlist':['601728']},at)[0]
    assert row['final_status']=='数据源不一致' and row['confirmation']=='未确认'
    assert not row['priority_candidate'] and not sent

def test_missing_second_source_blocks_confirmation(tmp_path,monkeypatch):
    at=datetime(2026,10,23,16,tzinfo=TZ); p,s,q=prepared(tmp_path,at)
    p.cross_validate=lambda *a:dict(passed=False,status='数据不足')
    monkeypatch.setattr('monitor.engine.notify',lambda *a:pytest.fail('不得通知'))
    row=scan(p,s,DEFAULT|{'watchlist':['601728']},at)[0]
    assert row['final_status']=='数据不足' and row['confirmation']=='未确认'

def test_full_market_candidate_keeps_cross_gate_and_disables_alerts(tmp_path,monkeypatch):
    at=datetime(2026,10,23,16,tzinfo=TZ);p,s,q=prepared(tmp_path,at)
    p.cross_validate=lambda *a:p.validator.cross(q,q|{'origin':'B','source':'测试源B'})
    monkeypatch.setattr('monitor.engine.notify',lambda *a:pytest.fail('全市场扫描默认不得发送通知'))
    rows=scan(p,s,DEFAULT|{'watchlist':['601728'],'notify_enabled':False},at,preselect=True)
    row=rows[0]
    assert not row['preliminary'] and row['final_status']=='收盘确认'
    assert row['cross']['passed'] and s.history('signal')

def test_one_stock_failure_does_not_stop_scan(tmp_path,monkeypatch):
    at=datetime(2026,10,23,16,tzinfo=TZ); p,s,q=prepared(tmp_path,at)
    daily=p.daily
    def fetch(code,at):
        if code=='000498': raise RuntimeError('单股接口错误')
        return daily(code,at)
    p.daily=fetch; p.cross_validate=lambda *a:dict(passed=False,status='数据不足')
    monkeypatch.setattr('monitor.engine.notify',lambda *a:pytest.fail('不得通知'))
    rows=scan(p,s,DEFAULT|{'watchlist':['000498','601728','002376']},at)
    assert {r['code'] for r in rows}=={'000498','601728','002376'}
    assert rows[0]['status']=='数据错误'
    assert any(r.get('kind')=='突破' for r in rows if r['code']=='002376')
