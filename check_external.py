"""兼容旧版检查入口：逐股检查全部行情源，不发通知。"""
import json
from pathlib import Path
from monitor.cli import probe
if __name__ == '__main__':
    result = probe(all_sources=True)
    text = json.dumps(result,ensure_ascii=False,indent=2,default=str)
    Path(__file__).with_name('validation-live.json').write_text(text,encoding='utf-8')
    print(text)
