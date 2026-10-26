import pytest
from monitor.config import DEFAULT
from monitor.store import Store
from monitor.full_market import MarketQueue

def test_retry_failed_bounded_and_preserves_success(tmp_path):
    q=MarketQueue(Store(path=tmp_path/'db'))
    u=dict(time='2026-10-26',source='模拟',demo=True,complete=False,
           stocks=[dict(code='600000',name='模拟0'),dict(code='600001',name='模拟1')])
    job=q.create(u,DEFAULT,'模拟阶段')
    with pytest.raises(ValueError):q.retry_failed(job)
    with q.store.connect() as db:
        db.execute("UPDATE market_jobs SET status='completed' WHERE id=?",(job,))
        db.execute("UPDATE market_items SET state='failed',attempts=1 WHERE code='600000'")
        db.execute("UPDATE market_items SET state='done',attempts=1 WHERE code='600001'")
    assert q.retry_failed(job)==1
    assert q.counts(job)=={'pending':1,'done':1}
    with q.store.connect() as db:
        db.execute("UPDATE market_jobs SET status='completed' WHERE id=?",(job,))
        db.execute("UPDATE market_items SET state='failed',attempts=2 WHERE code='600000'")
    assert q.retry_failed(job)==0
