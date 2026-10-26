"""全市场用小型模拟队列验证持久性，不向几千个真实接口发测试请求。"""
import json
from datetime import datetime
import pytest
from monitor.config import DEFAULT
from monitor.store import Store
from monitor.full_market import MarketQueue,run_batch
from monitor.universe import normalize,refresh
from monitor.market import Provider,TZ
from monitor.engine import scan

def universe(n=6):
    return dict(time='2026-10-26T14:00:00+08:00',source='测试模拟名录',complete=True,demo=True,
                stocks=[dict(code=f'{600000+i:06}',name=f'模拟股票{i}') for i in range(n)])

@pytest.fixture
def queue(tmp_path,monkeypatch):
    q=MarketQueue(Store(path=tmp_path/'market.sqlite3'))
    monkeypatch.setattr('monitor.full_market.context_at',lambda *a:'测试阶段')
    def fake(provider,store,cfg,**kwargs):
        assert kwargs['preselect'] and not cfg['notify_enabled']
        return [dict(code=cfg['watchlist'][0],final_status='观察',kind='突破')]
    monkeypatch.setattr('monitor.full_market.scan',fake)
    return q

def create(q,n=6,**kw):return q.create(universe(n),DEFAULT|kw,'测试阶段')

def test_large_pool_and_duplicate_active_job(queue):
    job=create(queue,5001)
    assert queue.counts(job)=={'pending':5001}
    assert len(json.loads(queue.latest()['config'])['watchlist'])==6
    with pytest.raises(ValueError,match='未结束'):create(queue)

def test_batches_persist_and_resume(queue):
    job=create(queue,5,market_batch_size=2)
    assert run_batch(queue,object())==2
    q=MarketQueue(Store(path=queue.store.path))
    assert q.counts(job)=={'done':2,'pending':3}
    assert run_batch(q,object())==2
    assert run_batch(q,object())==1
    assert q.status(job)=='completed' and q.counts(job)=={'done':5}

def test_pause_resume_cancel(queue):
    job=create(queue)
    queue.control(job,'pause');assert run_batch(queue,object())==0
    queue.control(job,'resume');assert run_batch(queue,object())==6
    # 已完成的任务不可被误恢复为待执行。
    queue.control(job,'resume');assert queue.status(job)=='completed'
    job=create(queue);queue.control(job,'cancel');assert run_batch(queue,object())==0

def test_pause_waits_current_stock(queue,monkeypatch):
    job=create(queue)
    def fake(*a,**kw):
        queue.control(job,'pause')
        return [dict(final_status='观察')]
    monkeypatch.setattr('monitor.full_market.scan',fake)
    assert run_batch(queue,object())==1
    assert queue.counts(job)=={'done':1,'pending':5} and queue.status(job)=='paused'

def test_interrupted_item_recovers(queue):
    job=create(queue,2)
    with queue.store.connect() as db:
        db.execute("UPDATE market_items SET state='running' WHERE job=? AND code='600000'",(job,))
    assert run_batch(queue,object())==2
    assert queue.counts(job)=={'done':2}

def test_stock_failure_isolated(queue,monkeypatch):
    job=create(queue,3)
    def fake(provider,store,cfg,**kwargs):
        if cfg['watchlist'][0]=='600001':raise RuntimeError('模拟单股错误')
        return [dict(final_status='收盘确认')]
    monkeypatch.setattr('monitor.full_market.scan',fake)
    assert run_batch(queue,object())==3
    assert queue.counts(job)=={'candidate':2,'failed':1}
    assert len(queue.results(job,candidates=True))==2
    assert any(x['rows'][0].get('error') for x in queue.results(job))

def test_new_phase_expires_job(queue,monkeypatch):
    job=create(queue)
    monkeypatch.setattr('monitor.full_market.context_at',lambda *a:'下一行情阶段')
    assert run_batch(queue,object())==0
    assert queue.status(job)=='expired' and queue.counts(job)=={'pending':6}
    queue.control(job,'resume');assert queue.status(job)=='expired'

def test_filters_and_dedup(queue):
    u=universe(1);u['stocks'] += [dict(code='000001',name='ST模拟'),dict(code='920001',name='北交模拟')]
    job=queue.create(u,DEFAULT,'测试阶段',exchanges=('sh','sz'),include_st=False)
    assert queue.counts(job)=={'pending':1}
    with pytest.raises(ValueError):normalize([dict(code='510300',name='ETF')])
    assert len(normalize(universe(1)['stocks']*2))==1

def test_universe_partial_explicit(tmp_path,monkeypatch):
    import monitor.universe as module
    class Transport:
        def __init__(self,*a):self.response_meta=dict(from_cache=False,fetched_at='2026-10-26T14:00:00+08:00')
        def request(self,name,kwargs,ttl):
            if name=='stock_info_sz_name_code':return [{'A股代码':'000001','A股简称':'模拟深市'}]
            raise RuntimeError('模拟其余交易所断开')
    monkeypatch.setattr(module,'AKTransport',Transport)
    s=Store(path=tmp_path/'u.db');u=refresh(s,DEFAULT)
    assert not u['complete'] and len(u['stocks'])==1
    assert sum(x['ok'] for x in u['segments'])==1
    assert s.get('market:universe')[1]['stocks'][0]['code']=='000001'

def test_preselection_without_quote(tmp_path,monkeypatch):
    s=Store(path=tmp_path/'db');p=Provider(s,DEFAULT,True)
    monkeypatch.setattr('monitor.engine.evaluate',lambda *a:dict(status='未通过',reasons=['模拟不满足']))
    monkeypatch.setattr(p,'quote',lambda *a:pytest.fail('未通过初筛不得请求快照'))
    rows=scan(p,s,DEFAULT|{'watchlist':['601728']},datetime(2026,10,23,16,tzinfo=TZ),preselect=True)
    assert all(r['preliminary'] and r['final_status']=='观察' for r in rows)
    assert all(r['quality']=='日K初筛（非实时）' and not r['is_realtime'] for r in rows)

def test_intraday_cache_cannot_turn_into_complete_after_close(tmp_path):
    s=Store(path=tmp_path/'db');p=Provider(s,DEFAULT,True)
    at=datetime(2026,10,23,14,tzinfo=TZ);d=p.daily('601728',at)
    later=at.replace(hour=16)
    checked=p.validator.history(d,'601728','模拟','demo',dict(from_cache=True,fetched_at=at.isoformat()),later,p.calendar())
    assert not bool(checked.is_complete.iloc[-1]) and checked.attrs['stale']
