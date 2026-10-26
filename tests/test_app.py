from streamlit.testing.v1 import AppTest
import pytest

@pytest.fixture(autouse=True)
def isolated_app(tmp_path,monkeypatch):
    monkeypatch.setattr('monitor.config.ROOT',tmp_path)
    monkeypatch.setattr('monitor.store.ROOT',tmp_path)

def test_dashboard_boot():
    app=AppTest.from_file('../app.py').run(timeout=30)
    assert not app.exception

def test_demo_scan():
    app=AppTest.from_file('../app.py').run(timeout=30)
    app.toggle[0].set_value(True).run()
    app.button(key='scan').click().run(timeout=30)
    assert not app.exception
    assert len(app.dataframe)>0

def test_full_market_demo():
    app=AppTest.from_file('../app.py').run(timeout=30)
    app.toggle(key='demo').set_value(True).run()
    app.radio(key='page').set_value('全A股扫描').run()
    app.button(key='market_universe').click().run(timeout=30)
    assert not app.exception
    app.button(key='market_create').click().run(timeout=30)
    assert not app.exception and len(app.progress)>0
    [b for b in app.button if b.label=='手动处理一批'][0].click().run(timeout=30)
    assert not app.exception

