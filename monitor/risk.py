from decimal import Decimal, ROUND_HALF_UP
import math

def tick(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))

def fill_price(price,slippage,buy=True):
    """先以十进制计算滑点，再按分报价，避免5×1.001的二进制误差。"""
    factor=Decimal(1)+(Decimal(str(slippage)) if buy else -Decimal(str(slippage)))
    return tick(Decimal(str(price))*factor)

def fee(value,cfg,sell=False):
    amount=Decimal(str(value))
    commission=max(Decimal(str(cfg['minimum_commission'])),amount*Decimal(str(cfg['commission'])))
    rate=Decimal(str(cfg['other_fee']))+(Decimal(str(cfg['tax'])) if sell else Decimal(0))
    return tick(commission+amount*rate)

def assess(price,stop,cfg,*,name='',amount=0,change=None,code='',metadata_known=False):
    if not all(math.isfinite(v) for v in (price,stop,amount)) or not 0<stop<price:
        return dict(eligible=False,shares=0,reasons=['无有效技术失效位'])
    entry=fill_price(price,cfg['slippage'])
    exit_price=fill_price(stop,cfg['slippage'],False)
    quantity=0
    for q in range(100,int(cfg['capital']/entry)//100*100+1,100):
        cost=q*entry+fee(q*entry,cfg)
        loss=cost-(q*exit_price-fee(q*exit_price,cfg,True))
        if cost<=cfg['capital'] and loss<=cfg['risk']: quantity=q
    q=quantity or 100
    cost=q*entry+fee(q*entry,cfg)
    loss=cost-(q*exit_price-fee(q*exit_price,cfg,True))
    target=tick(entry+cfg['reward_multiple']*(entry-stop))
    target_fill=fill_price(target,cfg['slippage'],False)
    gain=q*target_fill-fee(q*target_fill,cfg,True)-cost
    ratio=gain/loss if loss>0 else 0
    reasons=[]
    if quantity==0: reasons.append('资金或含费用风险预算不足100股')
    if ratio<cfg.get('min_reward_risk',1.5): reasons.append('扣费后风险收益比低于配置阈值')
    if 'ST' in name.upper(): reasons.append('ST风险，禁止作为可执行候选')
    if amount<cfg['min_amount']: reasons.append('流动性不足或成交额未知')
    if not metadata_known: reasons.append('停牌/涨跌停/上市阶段/财报风险未全部核实，需人工核验')
    if change is None: reasons.append('涨跌幅未知')
    elif abs(change)>=4.5: reasons.append('接近价格限制的保守筛查，需核实实际涨跌停价')
    if code.startswith(('68','30','8','4','92')): reasons.append('特殊板块交易门槛及价格限制需独立核验')
    return dict(eligible=not reasons,priority_eligible=not reasons,budget_pass=bool(quantity>0 and ratio>=cfg.get('min_reward_risk',1.5)),
        reward_risk_raw=ratio,shares=quantity,illustration_shares=q,entry=entry,stop=tick(stop),target=target,
        stop_basis=f'最近{cfg.get("stop_lookback",10)}根已可见日K最低价（不按预算倒推）',
        target_basis=f'假设入场价 + {cfg["reward_multiple"]} ×（假设入场价 - 技术失效位），净收益再扣滑点和费用',
        estimated_loss=round(loss,2),estimated_profit=round(gain,2),reward_risk=round(gain/loss,2) if loss>0 else None,
        reasons=reasons,exit_conditions='次日起跌破失效位或日线MA10；参考目标价。T+1及跌停可能使止损无法成交。')
