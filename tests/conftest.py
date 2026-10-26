import pytest

@pytest.fixture(autouse=True)
def notifications_disabled(monkeypatch):
    monkeypatch.setenv('DESKTOP_NOTIFY','0')
    monkeypatch.delenv('NOTIFY_WEBHOOK',raising=False)
