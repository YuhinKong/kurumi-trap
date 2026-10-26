"""首页重检历史扫描快照的年龄，避免上一次扫描结果永久显示有效。"""
from copy import deepcopy

def refresh_quality(rows,validator,at,calendar):
    refreshed=deepcopy(rows)
    for row in refreshed:
        try:
            q=row.get('quote')
            if not q: continue
            q=validator.quote(q,at,calendar)
            row.update(quote=q,quality=q['quality'],data_age_seconds=q['data_age_seconds'],
                       is_realtime=False)  # 已保存的扫描展示是历史快照
            if not q.get('fresh'):
                row.update(final_status='数据过期',confirmation='未确认',priority_candidate=False)
        except Exception:
            row.update(final_status='数据错误',confirmation='未确认',quality='新鲜度复核失败',priority_candidate=False)
    return refreshed
