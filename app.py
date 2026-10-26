"""中文界面：规则状态、数据质量、候选确认、风险筛选分别展示。"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from monitor.config import load,save,NAMES
from monitor.market import Provider,now,complete_daily,weekly
from monitor.store import Store
from monitor.engine import scan
from monitor.strategy import indicators
from monitor.backtest import run
from monitor.locking import BusyError
from monitor.view import refresh_quality

st.set_page_config(page_title='股票Agent · V0.1增强版',layout='wide')
st.title('股票监控Agent · V0.1增强版')
st.caption('A股规则研究 · 不自动交易 · 不保证盈利 · 无本地行情服务依赖 · ETF暂不支持')
try: cfg=load()
except ValueError as e: st.error(str(e)); st.stop()
demo=st.sidebar.toggle('模拟测试模式',value=False,key='demo')
page=st.sidebar.radio('页面',['行情总览','全A股扫描','K线与回测','历史信号','系统状态/日志'],key='page')
if demo: st.warning('模拟模式：价格和日历均为测试生成，不是真实行情，不产生正式候选，不发送通知。')
store=Store('demo' if demo else 'real'); provider=Provider(store,cfg,demo)
with st.sidebar.form('parameters'):
    symbols=st.text_area('自选股：六位股票代码，用逗号分隔',','.join(cfg['watchlist']))
    draft=cfg.copy()
    for key,label in [('capital','总资金（元）'),('risk','单笔风险预算（元）'),('min_reward_risk','最低净风险收益比'),('breakout_volume','突破量比下限'),('pullback_volume','回踩量比上限'),('pullback_tolerance','回踩距离比例'),('cross_tolerance','双源价差上限（0.003=0.3%）'),('quote_max_age','盘中最大数据年龄（秒）')]:
        draft[key]=st.number_input(label,value=float(cfg[key]),min_value=0.001)
    if st.form_submit_button('保存参数'):
        draft['watchlist']=[x.strip() for x in symbols.replace('，',',').split(',') if x.strip()]
        try: save(draft); cfg=load(); st.success('已保存；重新扫描生效')
        except ValueError as e: st.error(str(e))

if page=='全A股扫描':
    from monitor.market_ui import render
    render(cfg,demo)
    st.stop()

if page=='系统状态/日志':
    st.subheader('运行状态')
    beat=store.get('heartbeat')
    if beat:
        info=beat[1]; age=(now()-pd.Timestamp(info['time']).to_pydatetime()).total_seconds()
        state='运行中' if info.get('status')=='running' and age<120 else '已停止或心跳过期'
        st.write(f'自动监控：{state}；心跳时间：{info["time"]}；PID：{info.get("pid","未知")}')
    else: st.info('未发现增强版后台心跳。打开网页不会自动启动监控；请双击“2-启动自动监控.cmd”。')
    st.write('日K：AKShare/东方财富 → 腾讯 → AKShare/新浪；快照：腾讯 → 新浪。')
    st.caption('系统没有安装后台服务或开机任务。电脑关闭、休眠或进程停止后不再监控。')
    if st.button('检查自选股数据源（真实请求）',disabled=demo,key='probe'):
        from monitor.cli import probe
        with st.spinner('逐股实测，不发送通知…'): report=probe(cfg,store)
        st.dataframe(pd.DataFrame(report['stocks']),width='stretch')
    logs=store.history('log')
    st.dataframe(pd.DataFrame(logs),width='stretch') if logs else st.success('暂无运行日志')
    st.stop()

if page=='历史信号':
    signals=[r for r in store.history('signal') if r.get('version')=='v01-enhanced-1']
    if signals:
        st.dataframe(pd.DataFrame([{k:r.get(k) for k in ('code','name','kind','final_status','confirmation','price','bar_time','source','quote_source')} for r in signals]),width='stretch')
    else: st.info('暂无增强版真实候选。旧版扫描/信号仍保存在数据库，未将其冒充新版已验证结果。')
    st.stop()

if page=='行情总览':
    if st.button('立即扫描',type='primary',key='scan'):
        try:
            with st.spinner('逐股获取并验证行情；请勿重复点击…'): scan(provider,store,cfg)
            st.success('扫描完成。规则通过不等于可以买入，请看候选确认与风险原因。')
        except BusyError as e: st.warning(str(e))
    history=store.history(); rows=history[0] if history else []
    rows=[r for r in rows if r.get('version')=='v01-enhanced-1']
    if rows and not demo:
        try: rows=refresh_quality(rows,provider.validator,now(),provider.calendar())
        except Exception as e: st.error('无法复核行情新鲜度：'+str(e)); rows=[]
    st.caption('总览是最近一次扫描快照；刷新页面会重算年龄，不会自动发起扫描。日K来源与快照来源分别展示。')
    kind=st.selectbox('候选类型',['全部','突破','回踩'])
    only=st.checkbox('只看规则通过（仍须验证行情和风险）')
    priority=st.checkbox('只看风险检查通过的优先候选')
    selected=[r for r in rows if (kind=='全部' or r.get('kind')==kind) and (not only or r.get('status')=='通过') and (not priority or r.get('priority_candidate'))]
    overview=[]
    for code in cfg['watchlist']:
        group=[r for r in selected if r['code']==code]
        if not group: continue
        r=group[0]; signals={x.get('kind'):x for x in group}
        order={'数据错误':7,'数据源不一致':6,'数据过期':5,'收盘确认':4,'盘中预警':3,'数据不足':2,'观察':1}
        final=max((x['final_status'] for x in group),key=lambda s:order.get(s,0))
        risk=r.get('risk',{})
        trend=lambda key:'多头' if r.get(key) is True else '非多头' if r.get(key) is False else '数据不足'
        def rule_text(k):
            s=signals.get(k,{})
            return '规则通过，候选未确认' if s.get('status')=='通过' and s.get('confirmation')=='未确认' else s.get('status','—')
        overview.append({'股票':f'{code} {r.get("name",NAMES.get(code,""))}','快照价':r.get('price'),
            '行情时间':r.get('bar_time'),'快照来源':r.get('quote_source','不可用'),'日K来源':r.get('source','不可用'),
            '数据质量':r.get('quality',r.get('error','未知')),'日线趋势':trend('daily_trend'),'周线趋势':trend('weekly_trend'),
            '突破规则':rule_text('突破'),'回踩规则':rule_text('回踩'),'量比':r.get('volume_ratio'),
            '净风险收益比':risk.get('reward_risk'),'数值预算检查':'通过' if r.get('budget_pass') else '未通过/不足',
            '最终状态':final,'需人工核验风险':not risk.get('eligible',False),'缓存':r.get('from_cache'),
            '数据年龄秒':r.get('data_age_seconds')})
    if overview: st.dataframe(pd.DataFrame(overview),hide_index=True,width='stretch')
    else: st.info('暂无符合筛选条件的增强版结果。先关闭筛选，再点击立即扫描。')
    for code in cfg['watchlist']:
        group=[r for r in selected if r['code']==code]
        if not group: continue
        with st.expander(f'{code} {group[0].get("name","")} · 详细计算'):
            for r in group:
                st.markdown(f'**{r.get("kind","")}：{r["final_status"]}；候选确认：{r["confirmation"]}**')
                if r.get('error'): st.error(r['error'])
                for reason in r.get('reasons',[]): st.write('• '+reason)
                calc=r.get('calculations',{})
                if calc:
                    st.dataframe(pd.DataFrame({'日线MA':calc['daily_ma'],'完整周线MA':calc['weekly_ma']}))
                    st.write(f'前20日最高价 {calc["previous_20_high"]:.3f}；前5日均量 {calc["previous_5_volume"]:.1f}手；日K策略价 {calc["close"]:.3f}')
                if r.get('daily_last'): st.dataframe(pd.DataFrame([r['daily_last']]),hide_index=True)
                risk=r.get('risk',{})
                st.write(f'假设入场 {risk.get("entry","—")}；技术失效位 {risk.get("stop","—")}；公式参考目标 {risk.get("target","—")}')
                st.caption(str(risk.get('stop_basis',''))+'；'+str(risk.get('target_basis','')))
                st.write(f'可负担股数 {risk.get("shares",0)}；预估损失 {risk.get("estimated_loss","—")}；预估净收益 {risk.get("estimated_profit","—")}')
                for reason in risk.get('reasons',[]): st.warning(reason)
                st.caption('可负担股数不是买入许可；为0时盈亏仅为100股示例。T+1、停牌、跳空和跌停可能令实际损失超过预算。')
                cross=r.get('cross',{})
                st.write('独立双源：',cross.get('status','尚未检查'),'；原因：',cross.get('reason','—'))
                if cross.get('quotes'):
                    st.dataframe(pd.DataFrame([{k:q.get(k) for k in ('source','price','bar_time','data_age_seconds','from_cache','quality')} for q in cross['quotes'] if q]),width='stretch')
                if (r.get('quote') or {}).get('clock_note'): st.info(r['quote']['clock_note'])
                if r.get('diagnostics'):
                    st.write('本股票接口失败或回退原因：'); st.dataframe(pd.DataFrame(r['diagnostics']),width='stretch')
                if r.get('calendar_status'): st.caption('交易日历：'+r['calendar_status'])
    st.stop()

code=st.selectbox('股票',cfg['watchlist'])
if st.button('加载日K',key='load_chart'):
    try: st.session_state[('chart',demo,code)]=provider.daily(code)
    except Exception as e: st.error(str(e))
frame=st.session_state.get(('chart',demo,code))
if frame is not None:
    st.caption(f'实际来源：{frame.attrs.get("source")}；获取时间：{frame.attrs.get("fetched_at")}；缓存：{frame.attrs.get("from_cache")}')
    try:
        cal=provider.calendar(); completed=complete_daily(frame,now(),cal,cfg['close_delay'])
        period=st.radio('图表周期',['日K（末根可能未完成）','完整周K'],horizontal=True)
        chart=indicators(frame if period.startswith('日') else weekly(completed,now(),cal))
        fig=make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[.75,.25])
        fig.add_trace(go.Candlestick(x=chart.date,open=chart.open,high=chart.high,low=chart.low,close=chart.close,name=period),row=1,col=1)
        for n in (5,10,20,30): fig.add_trace(go.Scatter(x=chart.date,y=chart[f'MA{n}'],name=f'MA{n}'),row=1,col=1)
        fig.add_trace(go.Bar(x=chart.date,y=chart.volume,name='成交量（手）'),row=2,col=1)
        fig.update_layout(height=650,xaxis_rangeslider_visible=False); st.plotly_chart(fig,width='stretch')
        kind=st.selectbox('回测策略',['突破','回踩'])
        if st.button('运行历史回测'):
            if not code.startswith(('60','00')): st.warning('本回测模型仅适用普通沪深主板研究')
            else:
                result=run(completed,cal,cfg,kind); st.warning(result['assumptions'])
                if result['equity']: st.line_chart(pd.DataFrame(result['equity']).set_index('date'))
                st.dataframe(result['trades']); st.write('期末未平仓：',result['open_position'])
    except Exception as e: st.error(str(e))
if st.button('加载可用5分钟线',disabled=demo):
    try: st.dataframe(provider.minutes(code).tail(100),width='stretch')
    except Exception as e: st.error('分钟线暂不可用：'+str(e))
