"""按交易时段运行的串行调度器；不创建系统服务或系统任务。"""
import os,time
from .config import load,ROOT
from .store import Store
from .market import Provider,now
from .engine import scan
from .locking import ProcessLock,BusyError

def due(at,calendar,delay):
    if not calendar or max(calendar)<at.date() or at.date() not in calendar: return None
    minute=at.hour*60+at.minute
    if 570<=minute<=690 or 780<=minute<900: return f'{at.date()}:盘中:{minute//5}'
    if 900+delay<=minute<=1020: return f'{at.date()}:收盘:{minute//5}'
    return None

def run_cycle(store,at=None):
    at=at or now(); cfg=load(); provider=Provider(store,cfg)
    key=due(at,provider.calendar(),cfg['close_delay'])
    if not key: return
    if ':收盘:' in key and store.get('v01e:close_done:'+str(at.date())): return
    if store.get('v01e:slot:'+key): return
    rows=scan(provider,store,cfg)
    store.put('v01e:slot:'+key,True)
    if ':收盘:' in key and rows and all(r.get('close_ready') for r in rows):
        store.put('v01e:close_done:'+str(at.date()),True)

def main():
    store=Store()
    with ProcessLock(ROOT/'data'/'scheduler.lock'):
        print('自动监控已启动。交易时段每5分钟扫描；Ctrl+C停止。仅本进程运行时有效。',flush=True)
        try:
            while True:
                store.put('heartbeat',dict(time=now().isoformat(),pid=os.getpid(),status='running'))
                try: run_cycle(store)
                except BusyError as e: store.event('log',dict(kind='busy',message=str(e)))
                except Exception as e: store.event('log',dict(kind='scheduler_error',message=str(e)))
                time.sleep(15)
        except KeyboardInterrupt: print('监控已停止。',flush=True)
        finally: store.put('heartbeat',dict(time=now().isoformat(),pid=os.getpid(),status='stopped'))

if __name__=='__main__': main()
