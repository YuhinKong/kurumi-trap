"""全市场持久队列：每股落库、断点恢复、串行限速，候选才请求双源快照。"""
import json,time,uuid,os
from .market import Provider,now
from .config import DEFAULT,load,ROOT
from .store import Store
from .engine import scan
from .locking import ProcessLock,BusyError
from .universe import normalize

class MarketQueue:
    def __init__(self,store):
        self.store=store
        with store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS market_jobs
                (id TEXT PRIMARY KEY,created TEXT,status TEXT,context TEXT,config TEXT,meta TEXT);
                CREATE TABLE IF NOT EXISTS market_items
                (job TEXT,code TEXT,name TEXT,exchange TEXT,state TEXT,attempts INTEGER DEFAULT 0,updated TEXT,result TEXT,
                 PRIMARY KEY(job,code));''')

    def latest(self):
        with self.store.connect() as db:
            r=db.execute('SELECT id,created,status,context,config,meta FROM market_jobs ORDER BY created DESC LIMIT 1').fetchone()
        return dict(zip(('id','created','status','context','config','meta'),r)) if r else None

    def create(self,universe,cfg,context,exchanges=('sh','sz','bj'),include_st=True):
        entries=[r for r in normalize(universe['stocks']) if r['exchange'] in exchanges and (include_st or 'ST' not in r['name'].upper())]
        if not entries: raise ValueError('筛选后股票池为空')
        job=uuid.uuid4().hex; stamp=now().isoformat()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM market_jobs WHERE status IN ('queued','running','paused')").fetchone():
                raise ValueError('已有未结束任务，请继续、取消后再创建')
            meta=dict(universe_time=universe['time'],universe_source=universe['source'],universe_complete=universe['complete'],
                      demo=universe.get('demo',False),exchanges=list(exchanges),include_st=include_st,count=len(entries))
            db.execute('INSERT INTO market_jobs VALUES(?,?,?,?,?,?)',(job,stamp,'queued',context,json.dumps(cfg,ensure_ascii=False),json.dumps(meta,ensure_ascii=False)))
            db.executemany('INSERT INTO market_items(job,code,name,exchange,state) VALUES(?,?,?,?,?)',[(job,r['code'],r['name'],r['exchange'],'pending') for r in entries])
        return job

    def status(self,job):
        with self.store.connect() as db:
            r=db.execute('SELECT status FROM market_jobs WHERE id=?',(job,)).fetchone()
        return r[0] if r else None

    def control(self,job,action):
        allowed={'pause':(('queued','running'),'paused'),'resume':(('paused',),'queued'),
                 'cancel':(('queued','paused','running'),'cancelled')}
        states,target=allowed[action]
        with self.store.connect() as db:
            db.execute('UPDATE market_jobs SET status=? WHERE id=? AND status IN ('+','.join('?' for _ in states)+')',(target,job,*states))

    def counts(self,job):
        with self.store.connect() as db:
            return dict(db.execute('SELECT state,count(*) FROM market_items WHERE job=? GROUP BY state',(job,)).fetchall())

    def retry_failed(self,job):
        """人工触发一次失败重试，不重扫成功项；每股每轮最多处理两次。"""
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            status=db.execute('SELECT status FROM market_jobs WHERE id=?',(job,)).fetchone()
            if not status or status[0] not in ('paused','completed'):
                raise ValueError('请先暂停或等本轮结束后重试；跨阶段过期任务需新建')
            count=db.execute("UPDATE market_items SET state='pending' WHERE job=? AND state='failed' AND attempts<2",(job,)).rowcount
            if count: db.execute("UPDATE market_jobs SET status='queued' WHERE id=?",(job,))
        return count

    def results(self,job,limit=200,offset=0,candidates=False):
        with self.store.connect() as db:
            sql='SELECT code,name,state,updated,result FROM market_items WHERE job=?'
            if candidates: sql+=" AND state='candidate'"
            rows=db.execute(sql+' ORDER BY code LIMIT ? OFFSET ?',(job,limit,offset)).fetchall()
        return [dict(code=c,name=n,state=s,updated=t,rows=json.loads(r) if r else []) for c,n,s,t,r in rows]

def context_at(provider,at=None):
    at=at or now(); cal=provider.calendar()
    day=provider.validator.expected_day(at,cal,include_partial=True)
    partial=day==at.date() and at.hour*60+at.minute<900+provider.cfg['close_delay']
    return f'{day}:{"盘中" if partial else "完整"}'

def run_batch(queue,provider=None):
    store=queue.store
    with ProcessLock(store.path.with_suffix('.market-worker.lock')):
        job=queue.latest()
        if not job or job['status'] not in ('queued','running'): return 0
        cfg=DEFAULT|json.loads(job['config']); meta=json.loads(job['meta'])
        # 全市场优先逐股腾讯历史；单次失败即转源，不让同一故障拖住几千只。
        if provider is None:
            provider=Provider(store,cfg|{'retries':1},meta['demo'])
            provider.sources.sort(key=lambda s:0 if s.origin=='tencent' else 1 if s.origin=='sina' else 2)
        with store.connect() as db:
            db.execute("UPDATE market_items SET state='pending' WHERE job=? AND state='running'",(job['id'],))
            db.execute("UPDATE market_jobs SET status='running' WHERE id=? AND status='queued'",(job['id'],))
        started=time.monotonic(); processed=0
        while processed<cfg['market_batch_size'] and time.monotonic()-started<cfg['market_batch_seconds']:
            if queue.status(job['id'])!='running': break
            if context_at(provider)!=job['context']:
                with store.connect() as db: db.execute("UPDATE market_jobs SET status='expired' WHERE id=? AND status='running'",(job['id'],))
                break
            with store.connect() as db:
                entry=db.execute("SELECT code,name FROM market_items WHERE job=? AND state='pending' ORDER BY code LIMIT 1",(job['id'],)).fetchone()
                if entry: db.execute("UPDATE market_items SET state='running',attempts=attempts+1 WHERE job=? AND code=?",(job['id'],entry[0]))
            if not entry: break
            code,name=entry
            store.put('market:heartbeat',dict(time=now().isoformat(),pid=os.getpid(),code=code,job=job['id']))
            try:
                rows=scan(provider,store,cfg|{'watchlist':[code],'notify_enabled':False},preselect=True)
                for r in rows:
                    if not r.get('name'): r['name']=name
                    r['scanned_at']=now().isoformat()
                state='failed' if any(r['final_status'] in ('数据错误','数据过期') for r in rows) else 'candidate' if any(r['final_status'] in ('盘中预警','收盘确认') for r in rows) else 'done'
            except Exception as e:
                state='failed'; rows=[dict(code=code,name=name,final_status='数据错误',error=str(e))]
                store.event('log',dict(kind='market_stock_error',code=code,error=str(e)))
            with store.connect() as db:
                db.execute('UPDATE market_items SET state=?,updated=?,result=? WHERE job=? AND code=?',
                    (state,now().isoformat(),json.dumps(rows,ensure_ascii=False,default=str),job['id'],code))
            processed+=1
        counts=queue.counts(job['id'])
        if not counts.get('pending') and not counts.get('running'):
            with store.connect() as db: db.execute("UPDATE market_jobs SET status='completed' WHERE id=? AND status='running'",(job['id'],))
        return processed

def main(demo=False):
    store=Store('market-demo' if demo else 'market-real'); queue=MarketQueue(store)
    with ProcessLock(ROOT/'data'/('market-demo-daemon.lock' if demo else 'market-daemon.lock')):
        print('全市场队列处理器已启动。先在网页创建任务；Ctrl+C停止，已完成记录保留。',flush=True)
        try:
            while True:
                try:
                    count=run_batch(queue)
                    if count: print(f'{now().isoformat()} 本批完成{count}只',flush=True)
                except BusyError: pass
                except Exception as e: store.event('log',dict(kind='market_worker_error',error=str(e)))
                time.sleep(load()['market_interval'])
        except KeyboardInterrupt: print('已停止；下次启动会断点续扫。',flush=True)
