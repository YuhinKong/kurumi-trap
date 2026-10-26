from datetime import datetime,timedelta
from pathlib import Path
import subprocess,json,time
import pandas as pd
import pytest
from monitor.config import DEFAULT,NAMES,ROOT,validate_config
from monitor.market import Provider,TZ,validate,complete_daily,weekly
from monitor.data_provider import DataProvider
from monitor.validator import DataValidator
from monitor.store import Store
from monitor.sources import HTTPClient,symbol
from monitor.locking import ProcessLock,BusyError
from monitor.risk import assess

AT=datetime(2026,10,23,14,tzinfo=TZ)
CAL=pd.bdate_range('2020-01-01','2030-12-31').date.tolist()

def snapshot(price=5,origin='tencent',**kw):
    return dict(code='000498',name='山东路桥',origin=origin,source=origin,price=price,open=5.,high=6.,low=4.,
        volume=10000.,amount=5e6,bar_time=AT.isoformat(),fetched_at=AT.isoformat(),from_cache=False)|kw

@pytest.mark.parametrize('code',NAMES)
def test_six_codes_metadata_and_ma(tmp_path,code):
    from monitor.strategy import indicators
    p=Provider(Store(path=tmp_path/'db'),DEFAULT,True); d=p.daily(code,AT)
    assert d.code.eq(code).all() and (d.high>=d[['open','close']].max(axis=1)).all()
    assert (d.low<=d[['open','close']].min(axis=1)).all() and (d.volume>=0).all()
    assert not d.is_complete.iloc[-1]
    for n in (5,10,20,30): assert indicators(d)[f'MA{n}'].iloc[-1]==pytest.approx(d.close.tail(n).mean())
    assert {'source','bar_time','fetched_at','timezone','is_complete','is_intraday','data_age_seconds','from_cache'}.issubset(d)

def test_stale_and_cache_not_realtime():
    v=DataValidator(DEFAULT)
    old=v.quote(snapshot(bar_time=(AT-timedelta(minutes=20)).isoformat()),AT,CAL)
    assert not old['fresh'] and not old['is_realtime']
    cached=v.quote(snapshot(from_cache=True),AT,CAL)
    assert cached['fresh'] and not cached['is_realtime']
    with pytest.raises(ValueError,match='未来'): v.quote(snapshot(bar_time=(AT+timedelta(seconds=1)).isoformat()),AT,CAL)

def test_dual_source_checks():
    v=DataValidator(DEFAULT); a=v.quote(snapshot(),AT,CAL)
    assert v.cross(a,v.quote(snapshot(5.01,origin='sina'),AT,CAL))['passed']
    assert v.cross(a,v.quote(snapshot(5.02,origin='sina'),AT,CAL))['status']=='数据源不一致'
    assert not v.cross(a,a)['passed']
    b=v.quote(snapshot(origin='sina',bar_time=(AT-timedelta(seconds=150)).isoformat()),AT,CAL)
    assert not v.cross(a,b)['passed']

class FakeSource:
    def __init__(self,name,df=None,fail=False): self.name=self.origin=name; self.df=df; self.fail=fail
    def daily(self,*a):
        if self.fail: raise RuntimeError('RemoteDisconnected')
        return self.df.copy(),dict(from_cache=False,fetched_at=AT.isoformat())

def test_fallback_and_short_history(tmp_path):
    store=Store(path=tmp_path/'db'); d=Provider(store,DEFAULT,True).daily('000498',AT)
    d=d[['date','open','high','low','close','volume','amount']]
    p=DataProvider(store,DEFAULT,sources=[FakeSource('ak',fail=True),FakeSource('short',d.tail(49)),FakeSource('tencent',d)])
    p._calendar=CAL
    out=p.daily('000498',AT)
    assert out.attrs['source']=='tencent' and out.attrs['history_sufficient']
    assert len(p.attempts)==2

def test_all_sources_failed_no_old_cache_substitution(tmp_path):
    store=Store(path=tmp_path/'db');store.put('old',{'price':5})
    p=DataProvider(store,DEFAULT,sources=[FakeSource('ak',fail=True),FakeSource('tencent',fail=True),FakeSource('sina',fail=True)])
    p._calendar=CAL
    with pytest.raises(RuntimeError,match='全部日K'): p.daily('000498',AT)

def test_http_cache_keeps_fetch_time(tmp_path):
    store=Store(path=tmp_path/'db');store.put('v2:cache','original')
    http=HTTPClient(store,DEFAULT)
    http.session.get=lambda *a,**kw:pytest.fail('有效缓存不应请求网络')
    text,meta=http.get('cache','unused',ttl=60)
    assert text=='original' and meta['from_cache']
    assert pd.Timestamp(meta['fetched_at']).timestamp()==pytest.approx(store.get('v2:cache')[0],abs=.01)

def test_clock_alignment_wait_never_uses_future(tmp_path,monkeypatch):
    import monitor.data_provider as module
    clock=[AT]; waits=[]
    def sleep(seconds): waits.append(seconds);clock[0]+=timedelta(seconds=seconds)
    class Source:
        name=origin='test'
        def quote(self,*a): return snapshot(origin='test',bar_time=(AT+timedelta(seconds=6)).isoformat()),dict(from_cache=False,fetched_at=AT.isoformat())
    monkeypatch.setattr(module,'now',lambda:clock[0]);monkeypatch.setattr(module.time,'sleep',sleep)
    p=DataProvider(Store(path=tmp_path/'db'),DEFAULT,quote_sources=[Source()]);p._calendar=CAL
    q=p.quote_from(p.quote_sources[0],'000498')
    assert waits and waits[0]>=6 and q['fresh'] and q.get('clock_note')
    assert pd.Timestamp(q['bar_time'])<=pd.Timestamp(q['validated_at'])
    assert q['fetched_at']==AT.isoformat()

def test_large_clock_offset_rejected_without_wait(tmp_path,monkeypatch):
    import monitor.data_provider as module
    class Source:
        name=origin='test'
        def quote(self,*a): return snapshot(bar_time=(AT+timedelta(minutes=2)).isoformat()),dict(from_cache=False,fetched_at=AT.isoformat())
    monkeypatch.setattr(module,'now',lambda:AT)
    monkeypatch.setattr(module.time,'sleep',lambda *a:pytest.fail('超出上限不应等待'))
    p=DataProvider(Store(path=tmp_path/'db'),DEFAULT);p._calendar=CAL
    with pytest.raises(ValueError,match='时间同步'):p.quote_from(Source(),'000498')

def test_process_lock_and_release(tmp_path):
    path=tmp_path/'lock'
    with ProcessLock(path):
        with pytest.raises(BusyError):
            with ProcessLock(path): pass
    with ProcessLock(path): pass

def test_signal_history_dedup(tmp_path):
    s=Store(path=tmp_path/'db');s.record_signal('key',{'code':'000498'});s.record_signal('key',{'code':'000498'})
    assert len(s.history('signal'))==1

def test_reward_risk_gate_uses_unrounded_ratio():
    c=DEFAULT|{'min_reward_risk':1.5}
    r=assess(5,4.8,c,amount=2e7,change=0,metadata_known=True)
    assert r['reward_risk_raw']<1.5 and not r['budget_pass']
    assert r['stop']==4.8 and '不按预算倒推' in r['stop_basis']

@pytest.mark.parametrize('code',['510300','159915','abc','123'])
def test_unsupported_codes_rejected(code):
    with pytest.raises(ValueError): symbol(code)

def test_invalid_configuration():
    with pytest.raises(ValueError):validate_config(DEFAULT|{'risk':2000})
    with pytest.raises(ValueError):validate_config(DEFAULT|{'cross_tolerance':float('nan')})

def test_weekly_excludes_truncated_first_week(tmp_path):
    p=Provider(Store(path=tmp_path/'db'),DEFAULT,True);d=p.daily('000498',AT)
    d=d.iloc[2:].reset_index(drop=True)
    w=weekly(complete_daily(d,AT,CAL),AT,CAL)
    assert w.date.iloc[0].date()>d.date.iloc[2].date()

def test_cmd_bytes_and_actual_parser():
    for f in ROOT.glob('*.cmd'):
        b=f.read_bytes();b.decode('ascii');assert b'\n' not in b.replace(b'\r\n',b'')
    result=subprocess.run(['cmd.exe','/d','/c','launcher.cmd','selftest'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'Launcher OK' in result.stdout

def test_no_removed_service_in_production():
    production=[ROOT/'app.py',*list((ROOT/'monitor').glob('*.py'))]
    assert all('stockdb' not in p.read_text(encoding='utf-8-sig').lower() for p in production)
    assert not (ROOT/'external').exists()
