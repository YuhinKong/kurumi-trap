"""操作系统文件锁：防止同一项目重复调度或手动/自动扫描同时进行。"""
import os
from pathlib import Path

class BusyError(RuntimeError): pass

class ProcessLock:
    def __init__(self,path): self.path=Path(path); self.handle=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        f=self.path.open('a+b'); f.seek(0)
        if self.path.stat().st_size==0: f.write(b'1'); f.flush()
        f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as e:
            f.close(); raise BusyError('已有同类任务运行，请等待完成；不要重复打开监控窗口') from e
        self.handle=f; return self
    def __exit__(self,*args):
        f=self.handle
        if not f: return
        f.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(f,fcntl.LOCK_UN)
        f.close(); self.handle=None
