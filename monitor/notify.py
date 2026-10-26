import os, json, urllib.request

def notify(store,key,message,demo=False):
    if demo or store.claimed(key): return
    delivered=False
    try:
        if os.getenv('DESKTOP_NOTIFY','0')=='1':
            from plyer import notification
            notification.notify(title='A股规则预警',message=message[:240],app_name='股票监控')
            delivered=True
        url=os.getenv('NOTIFY_WEBHOOK')
        if url:
            request=urllib.request.Request(url,data=json.dumps({'text':message}).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=10) as response:
                if response.status>=300: raise RuntimeError('通知HTTP失败')
            delivered=True
        if delivered: store.mark(key)
    except Exception as e: store.event('log',dict(notification_error=str(e)))
