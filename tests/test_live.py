import os
import pytest
import math
from monitor.config import DEFAULT,NAMES
from monitor.market import now,validate
from monitor.data_provider import DataProvider
from monitor.store import Store

pytestmark=[pytest.mark.live,pytest.mark.skipif(os.getenv('RUN_LIVE_TESTS')!='1',reason='设置RUN_LIVE_TESTS=1才请求真实接口')]

@pytest.mark.parametrize('code',NAMES)
def test_real_history_and_quote(tmp_path,code):
    p=DataProvider(Store(path=tmp_path/'db'),DEFAULT|{'retries':1})
    d=p.daily(code)
    validate(d)
    assert not d.attrs['stale'] and d.attrs['history_sufficient']
    q=p.quote(code)
    assert q and q['fresh']
    assert q['code']==code
    assert q['bar_time'] and q['fetched_at']
    result=p.cross_validate(code,q)
    # 真实价差超限时，正确行为就是阻止候选，不能要求供应商永远一致。
    assert len(result.get('quotes',[]))==2,result
    a,b=result['quotes']
    assert a['origin']!=b['origin'] and a['fresh'] and b['fresh'],result
    difference=abs(a['price']-b['price'])/min(a['price'],b['price'])
    assert math.isclose(result['difference'],difference,abs_tol=1e-12)
    assert result['passed']==(difference<=DEFAULT['cross_tolerance']),result
    assert result['status']==('通过' if result['passed'] else '数据源不一致'),result
