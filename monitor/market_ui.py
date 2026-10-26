"""全A股任务页面；仅用户点击创建任务后才处理股票，不自动全市场并发。"""
import json,math
import pandas as pd
import streamlit as st
from .store import Store
from .market import Provider,now
from .universe import refresh,normalize
from .full_market import MarketQueue,context_at,run_batch
from .config import save
from .locking import BusyError

LABELS={'queued':'等待处理','running':'处理中','paused':'已暂停','cancelled':'已取消','expired':'行情阶段已变化，需新建','completed':'本轮结束（不代表所有数据成功）'}

def flatten(item):
    rows=item['rows']
    risk=(rows[0].get('risk') or {}) if rows else {}
    return {'代码':item['code'],'名称':item['name'],'队列状态':item['state'],'处理时间':item['updated'],
            '突破（扫描时）':next((r.get('final_status') for r in rows if r.get('kind')=='突破'),'—'),
            '回踩（扫描时）':next((r.get('final_status') for r in rows if r.get('kind')=='回踩'),'—'),
            '数据来源':rows[0].get('source') if rows else None,
            '行情时间':rows[0].get('bar_time') if rows else None,
            '日K日期':rows[0].get('daily_bar_time') if rows else None,
            '初筛非实时':rows[0].get('preliminary') if rows else None,
            '净风险收益比':risk.get('reward_risk'),
            '错误':'; '.join(str(r.get('error','')) for r in rows if r.get('error'))}

def render(cfg,demo):
    st.subheader('全A股分批扫描')
    st.info('先更新沪深京名录，再创建任务。后台串行初筛；只有规则通过才查双源快照。全市场一轮可能数小时，结果逐股异步，不是同一时刻的实时全景。')
    store=Store('market-demo' if demo else 'market-real'); queue=MarketQueue(store)
    st.caption('全市场使用独立数据库，不覆盖6只自选股扫描。模拟模式只使用6只模拟名录，不冒充全市场。')
    if st.button('更新股票名录',key='market_universe'):
        try:
            with st.spinner('读取各交易所名录，最多四个有界请求…'): result=refresh(store,cfg,demo)
            st.success(f'取得{len(result["stocks"])}只股票')
        except Exception as e: st.error(str(e))
    cached=store.get('market:universe'); universe=cached[1] if cached else None
    if universe:
        st.write(f'名录：{len(universe["stocks"])}只；来源：{universe["source"]}；取得时间：{universe["time"]}')
        if not universe['complete']: st.warning('名录不完整：仅扫描已取得的部分，不能称为覆盖全部A股。')
        if universe.get('segments'): st.dataframe(pd.DataFrame(universe['segments']),hide_index=True,width='stretch')
    with st.expander('接口失败时导入股票名录CSV'):
        st.caption('UTF-8 CSV，列为code,name。仅支持A股代码。请从交易所等可信来源取得；导入名录不保证覆盖完整，不作为行情数据。')
        uploaded=st.file_uploader('CSV股票名录',type='csv')
        if st.button('保存导入名录',disabled=uploaded is None):
            try:
                df=pd.read_csv(uploaded,dtype=str)
                universe=dict(time=now().isoformat(),source='用户导入CSV（覆盖未核实）',complete=False,demo=demo,
                    stocks=normalize(df.to_dict('records')),segments=[])
                if demo: raise ValueError('模拟模式只使用模拟名录，请切换真实模式后导入真实名单')
                store.put('market:universe',universe);st.success(f'已导入{len(universe["stocks"])}只')
            except Exception as e: st.error('导入失败：'+str(e))
    markets=st.multiselect('交易所范围',['沪市','深市','北交所'],default=['沪市','深市','北交所'])
    include_st=st.checkbox('包含ST股票（仍会被风险检查标记）',value=True)
    st.caption('包含科创板和创业板的规则研究；特殊板块的交易门槛、价格限制仍须人工核验。ETF/B股不纳入。')
    if st.button('创建本轮扫描任务',disabled=not universe or not markets,key='market_create'):
        try:
            age=(now()-pd.Timestamp(universe['time']).to_pydatetime()).total_seconds()
            if age>7*86400: raise ValueError('名录超过7天，请先更新或重新导入')
            provider=Provider(store,cfg,demo)
            context=context_at(provider)
            exchanges=[{'沪市':'sh','深市':'sz','北交所':'bj'}[x] for x in markets]
            queue.create(universe,cfg,context,exchanges,include_st)
            st.success('任务已入队。双击“5-启动全A股扫描.cmd”处理；网页刷新不会丢进度。')
        except Exception as e: st.error(str(e))
    job=queue.latest()
    if not job: st.info('尚无全市场任务。');return
    meta=json.loads(job['meta']); counts=queue.counts(job['id']); total=meta['count']
    completed=sum(counts.get(k,0) for k in ('done','candidate','failed'))
    st.write(f'任务{job["id"][:8]}：{LABELS[job["status"]]}；数据阶段：{job["context"]}；股票数：{total}')
    st.progress(completed/total,text=f'已处理{completed}/{total}；候选{counts.get("candidate",0)}；失败/过期{counts.get("failed",0)}；待处理{counts.get("pending",0)}')
    st.caption(f'每批最多{json.loads(job["config"])["market_batch_size"]}只。暂停在当前股票处理完成后生效；Ctrl+C/关机后下次可续扫。阶段变化会停止旧任务，避免拼接跨日/跨收盘结果。')
    a,b,c,d=st.columns(4)
    if a.button('暂停任务',disabled=job['status'] not in ('running','queued')): queue.control(job['id'],'pause');st.rerun()
    if b.button('继续任务',disabled=job['status']!='paused'): queue.control(job['id'],'resume');st.rerun()
    if c.button('取消本轮',disabled=job['status'] not in ('queued','running','paused')): queue.control(job['id'],'cancel');st.rerun()
    if d.button('刷新进度'): st.rerun()
    if st.button('仅重试失败项（每股本轮最多两次）',disabled=job['status'] not in ('paused','completed')):
        try:
            if context_at(Provider(store,cfg,demo))!=job['context']:raise ValueError('行情阶段已变化，请新建任务')
            count=queue.retry_failed(job['id']);st.success(f'重新入队{count}只；成功项保留')
        except Exception as e:st.error(str(e))
    if st.button('手动处理一批',disabled=job['status'] not in ('queued','running')):
        try:
            with st.spinner('正在处理一批，结果逐股保存…'): run_batch(queue)
            st.rerun()
        except BusyError as e: st.warning(str(e))
        except Exception as e: st.error(str(e))
    beat=store.get('market:heartbeat')
    if beat: st.caption(f'最近处理心跳：{beat[1]["time"]}；股票{beat[1]["code"]}。这是历史心跳，不保证进程仍存活。')
    candidates=st.checkbox('仅显示扫描时曾通过行情校验的历史候选',key='market_candidates')
    page=int(st.number_input('结果页（每页100只）',min_value=1,max_value=max(1,math.ceil(total/100)),value=1))
    items=queue.results(job['id'],100,(page-1)*100,candidates)
    st.caption('候选仍需风险核验；旧候选不会自动保持新鲜。加入自选后重新扫描，获取当前确认结果。')
    st.dataframe(pd.DataFrame([flatten(x) for x in items]),hide_index=True,width='stretch')
    choices=[x['code'] for x in items if x['rows']]
    if choices:
        code=st.selectbox('查看本页股票详细计算',choices)
        item=next(x for x in items if x['code']==code)
        with st.expander(f'{code} {item["name"]} · 规则与风险'):
            for row in item['rows']:
                st.write('扫描时记录：',row.get('kind',''),row.get('final_status'),row.get('confirmation','未确认'))
                for reason in row.get('reasons',[]):st.write('• '+reason)
                if row.get('error'):st.error(row['error'])
                risk=row.get('risk',{})
                if risk:st.write('风险原因：','；'.join(risk.get('reasons',[])));st.write('失效位：',risk.get('stop'),'目标假设：',risk.get('target'),'依据：',risk.get('stop_basis'))
            if st.button('加入自选股（需重新扫描确认）'):
                try: save(cfg|{'watchlist':list(dict.fromkeys(cfg['watchlist']+[code]))});st.success('已加入自选，请回行情总览重新扫描')
                except ValueError as e:st.error(str(e))
    if st.button('生成本轮CSV导出'):
        export=pd.DataFrame([flatten(x) for x in queue.results(job['id'],total)])
        st.download_button('下载CSV',export.to_csv(index=False).encode('utf-8-sig'),f'A股扫描-{job["id"][:8]}.csv','text/csv')
