
"""
Execution Engine v0.5 scaffold.

IMPORTANT:
Real order submission is intentionally hard-disabled in v0.5.
This module validates whether a classic-arbitrage signal is fresh enough and
large enough to become an execution candidate. The next activation step should
only happen after authenticated balance/fee/precision checks pass on each
specific account.
"""
import time

class ExecutionBlocked(RuntimeError): pass

def preflight(op, live_quotes, capital, min_edge_pct, max_quote_age_ms):
    now=int(time.time()*1000)
    buy=live_quotes.get((op.buy_exchange,op.asset))
    sell=live_quotes.get((op.sell_exchange,op.asset))
    if not buy or not sell:
        return False,"Нет обеих live-котировок"
    age=max(now-buy.recv_ts_ms,now-sell.recv_ts_ms)
    if age>max_quote_age_ms:
        return False,f"Котировка устарела: {age} мс"
    if op.net_edge_pct<min_edge_pct:
        return False,f"NET edge {op.net_edge_pct:.3f}% ниже порога {min_edge_pct:.3f}%"
    if capital<=0:return False,"Неверный капитал"
    return True,"Preflight OK"

def submit_live_orders(*args,**kwargs):
    raise ExecutionBlocked(
        "LIVE-ордера в v0.5 заблокированы. Сначала подключите API, проверьте "
        "балансы/комиссии/точность объёмов и PAPER execution."
    )
