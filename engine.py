
from __future__ import annotations
import requests
from dataclasses import dataclass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

TIMEOUT = 9
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ArbitrageRadar/0.3"})
KUCOIN_FUT = {"BTC":"XBTUSDTM","ETH":"ETHUSDTM","SOL":"SOLUSDTM","XRP":"XRPUSDTM","DOGE":"DOGEUSDTM"}

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def get(url, params=None):
    r = SESSION.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

@dataclass
class Quote:
    exchange: str
    asset: str
    symbol: str
    bid: float
    ask: float
    last: float
    funding_rate: float
    interval_hours: float
    next_funding_ms: int | None
    ts: str
    @property
    def funding_per_hour(self): return self.funding_rate / self.interval_hours
    @property
    def funding_apr_pct(self): return self.funding_per_hour * 24 * 365 * 100

@dataclass
class Opportunity:
    asset: str
    long_exchange: str
    short_exchange: str
    long_symbol: str
    short_symbol: str
    gross_spread_per_hour: float
    gross_apr_pct: float
    est_total_cost: float
    break_even_hours: float
    entry_price_gap_pct: float
    long_ask: float
    short_bid: float
    ts: str
    def net_return_pct(self, hours): return (self.gross_spread_per_hour*hours-self.est_total_cost)*100
    def net_pnl(self, capital, hours): return capital*(self.gross_spread_per_hour*hours-self.est_total_cost)
    def status(self, min_apr, max_be): return "CANDIDATE" if self.gross_apr_pct>=min_apr and self.break_even_hours<=max_be else "WATCH"

@dataclass
class BasisOpportunity:
    exchange: str
    asset: str
    spot_ask: float
    perp_bid: float
    basis_pct: float
    funding_apr_pct: float
    est_total_cost: float
    simple_net_basis_pct: float
    ts: str

def fetch_bybit(asset):
    s=f"{asset}USDT"
    t=get("https://api.bybit.com/v5/market/tickers",{"category":"linear","symbol":s})["result"]["list"][0]
    i=get("https://api.bybit.com/v5/market/instruments-info",{"category":"linear","symbol":s})["result"]["list"][0]
    return Quote("Bybit",asset,s,float(t["bid1Price"]),float(t["ask1Price"]),float(t["lastPrice"]),float(t["fundingRate"]),float(i["fundingInterval"])/60,int(t["nextFundingTime"]) if t.get("nextFundingTime") else None,now_iso())

def fetch_okx(asset):
    s=f"{asset}-USDT-SWAP"
    f=get("https://www.okx.com/api/v5/public/funding-rate",{"instId":s})["data"][0]
    t=get("https://www.okx.com/api/v5/market/ticker",{"instId":s})["data"][0]
    ft, nft=int(f["fundingTime"]),int(f["nextFundingTime"])
    ih=(nft-ft)/3600000
    return Quote("OKX",asset,s,float(t["bidPx"]),float(t["askPx"]),float(t["last"]),float(f["fundingRate"]),ih if ih>0 else 8,nft,now_iso())

def fetch_mexc(asset):
    s=f"{asset}_USDT"
    f=get(f"https://contract.mexc.com/api/v1/contract/funding_rate/{s}")["data"]
    t=get("https://contract.mexc.com/api/v1/contract/ticker",{"symbol":s})["data"]
    return Quote("MEXC",asset,s,float(t["bid1"]),float(t["ask1"]),float(t["lastPrice"]),float(f["fundingRate"]),float(f["collectCycle"]),int(f["nextSettleTime"]) if f.get("nextSettleTime") else None,now_iso())

def fetch_kucoin(asset):
    s=KUCOIN_FUT.get(asset,f"{asset}USDTM")
    f=get(f"https://api-futures.kucoin.com/api/v1/funding-rate/{s}/current")["data"]
    t=get("https://api-futures.kucoin.com/api/v1/ticker",{"symbol":s})["data"]
    ih=float(f["granularity"])/3600000
    return Quote("KuCoin",asset,s,float(t["bestBidPrice"]),float(t["bestAskPrice"]),float(t["price"]),float(f["value"]),ih if ih>0 else 8,int(f["fundingTime"]) if f.get("fundingTime") else None,now_iso())

FETCHERS={"Bybit":fetch_bybit,"OKX":fetch_okx,"MEXC":fetch_mexc,"KuCoin":fetch_kucoin}

def collect_quotes(assets, exchanges):
    out={a:[] for a in assets}; errors=[]; jobs={}
    with ThreadPoolExecutor(max_workers=16) as pool:
        for a in assets:
            for e in exchanges:
                jobs[pool.submit(FETCHERS[e],a)]=(a,e)
        for fut in as_completed(jobs):
            a,e=jobs[fut]
            try: out[a].append(fut.result())
            except Exception as ex: errors.append(f"{a}/{e}: {ex}")
    return out, errors

def total_rt_cost(long_ex,short_ex,fees,slippage):
    return 2*fees[long_ex]+2*fees[short_ex]+slippage

def find_opportunities(quotes,fees,slippage):
    ops=[]; ts=now_iso()
    for a,rows in quotes.items():
        for L in rows:
            for S in rows:
                if L.exchange==S.exchange: continue
                ph=S.funding_per_hour-L.funding_per_hour
                if ph<=0: continue
                cost=total_rt_cost(L.exchange,S.exchange,fees,slippage)
                mid=(L.ask+S.bid)/2
                gap=(S.bid-L.ask)/mid*100 if mid else 0
                ops.append(Opportunity(a,L.exchange,S.exchange,L.symbol,S.symbol,ph,ph*24*365*100,cost,cost/ph,gap,L.ask,S.bid,ts))
    return sorted(ops,key=lambda x:x.gross_apr_pct,reverse=True)

def spot_quote(exchange, asset):
    if exchange=="Bybit":
        d=get("https://api.bybit.com/v5/market/tickers",{"category":"spot","symbol":f"{asset}USDT"})["result"]["list"][0]
        return float(d["bid1Price"]),float(d["ask1Price"])
    if exchange=="OKX":
        d=get("https://www.okx.com/api/v5/market/ticker",{"instId":f"{asset}-USDT"})["data"][0]
        return float(d["bidPx"]),float(d["askPx"])
    if exchange=="MEXC":
        d=get("https://api.mexc.com/api/v3/ticker/bookTicker",{"symbol":f"{asset}USDT"})
        return float(d["bidPrice"]),float(d["askPrice"])
    if exchange=="KuCoin":
        d=get("https://api.kucoin.com/api/v1/market/orderbook/level1",{"symbol":f"{asset}-USDT"})["data"]
        return float(d["bestBid"]),float(d["bestAsk"])
    raise ValueError(exchange)

def find_basis(quotes, fees, slippage):
    result=[]; jobs={}
    with ThreadPoolExecutor(max_workers=16) as pool:
        for asset,rows in quotes.items():
            for q in rows:
                jobs[pool.submit(spot_quote,q.exchange,asset)]=(asset,q)
        for fut in as_completed(jobs):
            asset,q=jobs[fut]
            try:
                sbid,sask=fut.result()
                basis=(q.bid-sask)/sask*100
                cost=4*fees[q.exchange]+slippage
                result.append(BasisOpportunity(q.exchange,asset,sask,q.bid,basis,q.funding_apr_pct,cost,basis-cost*100,now_iso()))
            except Exception:
                pass
    return sorted(result,key=lambda x:x.simple_net_basis_pct,reverse=True)


@dataclass
class ClassicArbitrage:
    asset: str
    buy_exchange: str
    sell_exchange: str
    buy_ask: float
    sell_bid: float
    gross_spread_pct: float
    est_total_cost: float
    net_edge_pct: float
    ts: str

    def net_pnl(self, capital):
        return capital * self.net_edge_pct / 100.0

    def status(self, min_net_edge_pct=0.10):
        return "CANDIDATE" if self.net_edge_pct >= min_net_edge_pct else "WATCH"


def collect_spot_quotes(assets, exchanges):
    """
    Returns:
      {asset: {exchange: {"bid": float, "ask": float}}}, errors
    """
    out = {a: {} for a in assets}
    errors = []
    jobs = {}

    with ThreadPoolExecutor(max_workers=16) as pool:
        for asset in assets:
            for exchange in exchanges:
                jobs[pool.submit(spot_quote, exchange, asset)] = (asset, exchange)

        for fut in as_completed(jobs):
            asset, exchange = jobs[fut]
            try:
                bid, ask = fut.result()
                out[asset][exchange] = {"bid": bid, "ask": ask}
            except Exception as exc:
                errors.append(f"{asset}/{exchange}: {exc}")

    return out, errors


def find_classic_arbitrage(spot_quotes, fees, slippage_total):
    """
    Classic cross-exchange spot arbitrage.

    BUY at ask on exchange A
    SELL at bid on exchange B

    Cost model:
    - one taker execution on BUY exchange
    - one taker execution on SELL exchange
    - slippage_total is treated as total execution slippage for both legs

    Withdrawal/rebalancing fees are intentionally NOT included yet because
    professional cross-exchange arbitrage normally uses pre-funded inventory.
    They will be modeled separately in a rebalancing module.
    """
    result = []
    ts = now_iso()

    for asset, by_exchange in spot_quotes.items():
        exchanges = list(by_exchange.keys())
        for buy_ex in exchanges:
            for sell_ex in exchanges:
                if buy_ex == sell_ex:
                    continue

                buy_ask = by_exchange[buy_ex]["ask"]
                sell_bid = by_exchange[sell_ex]["bid"]

                if buy_ask <= 0:
                    continue

                gross = (sell_bid - buy_ask) / buy_ask * 100.0
                cost = fees[buy_ex] + fees[sell_ex] + slippage_total
                net = gross - cost * 100.0

                result.append(ClassicArbitrage(
                    asset=asset,
                    buy_exchange=buy_ex,
                    sell_exchange=sell_ex,
                    buy_ask=buy_ask,
                    sell_bid=sell_bid,
                    gross_spread_pct=gross,
                    est_total_cost=cost,
                    net_edge_pct=net,
                    ts=ts,
                ))

    return sorted(result, key=lambda x: x.net_edge_pct, reverse=True)


def historical_funding(exchange, asset, days=7):
    now_ms=int(datetime.now(timezone.utc).timestamp()*1000)
    start_ms=now_ms-int(days*86400*1000)
    if exchange=="Bybit":
        s=f"{asset}USDT"
        d=get("https://api.bybit.com/v5/market/funding/history",{"category":"linear","symbol":s,"endTime":now_ms,"limit":200})
        return sorted([(int(x["fundingRateTimestamp"]),float(x["fundingRate"])) for x in d["result"]["list"] if int(x["fundingRateTimestamp"])>=start_ms])
    if exchange=="OKX":
        s=f"{asset}-USDT-SWAP"
        d=get("https://www.okx.com/api/v5/public/funding-rate-history",{"instId":s,"limit":"400"})
        return sorted([(int(x["fundingTime"]),float(x.get("realizedRate") or x["fundingRate"])) for x in d["data"] if int(x["fundingTime"])>=start_ms])
    if exchange=="KuCoin":
        s=KUCOIN_FUT.get(asset,f"{asset}USDTM")
        d=get("https://api-futures.kucoin.com/api/v1/contract/funding-rates",{"symbol":s,"from":start_ms,"to":now_ms})
        return sorted([(int(x["timepoint"]),float(x["fundingRate"])) for x in d["data"]])
    return []


def classic_from_live(live_quotes, fees, slippage_total, min_edge_pct=0.10, strong_edge_pct=0.25,
                      max_quote_age_ms=1500, signal_first_seen=None):
    """
    live_quotes: {(exchange,asset): LiveBBO-like object}
    Returns ClassicArbitrage objects enriched dynamically with:
      age_ms, bid_qty/ask_qty, signal_lifetime_s, action_comment
    """
    import time
    now=int(time.time()*1000);out=[]
    by_asset={}
    for (ex,a),q in live_quotes.items():
        by_asset.setdefault(a,{})[ex]=q
    if signal_first_seen is None: signal_first_seen={}
    active=set()
    for a, rows in by_asset.items():
        for bx,bq in rows.items():
            for sx,sq in rows.items():
                if bx==sx:continue
                gross=(sq.bid-bq.ask)/bq.ask*100 if bq.ask else -999
                cost=fees.get(bx,0)+fees.get(sx,0)+slippage_total
                net=gross-cost*100
                o=ClassicArbitrage(a,bx,sx,bq.ask,sq.bid,gross,cost,net,now_iso())
                o.age_ms=max(now-bq.recv_ts_ms,now-sq.recv_ts_ms)
                o.buy_ask_qty=getattr(bq,"ask_qty",0.0);o.sell_bid_qty=getattr(sq,"bid_qty",0.0)
                key=(a,bx,sx)
                is_signal=net>=min_edge_pct and o.age_ms<=max_quote_age_ms
                if is_signal:
                    active.add(key)
                    signal_first_seen.setdefault(key,now)
                    o.signal_lifetime_s=(now-signal_first_seen[key])/1000
                else:
                    signal_first_seen.pop(key,None);o.signal_lifetime_s=0.0
                if o.age_ms>max_quote_age_ms:
                    o.action_comment=f"🔴 НЕ ТОРГОВАТЬ — данные устарели ({o.age_ms} мс)"
                elif net<0:
                    o.action_comment="🔴 НЕ ТОРГОВАТЬ — после комиссий и slippage сделка убыточна"
                elif net<min_edge_pct:
                    o.action_comment=f"🟡 ЖДАТЬ — плюс есть, но NET {net:.3f}% ниже минимального {min_edge_pct:.3f}%"
                elif net<strong_edge_pct:
                    o.action_comment=f"🟢 РАССМОТРЕТЬ — BUY {bx}, SELL {sx}; сначала проверить балансы и глубину"
                else:
                    o.action_comment=f"🟢 СИЛЬНЫЙ СИГНАЛ — BUY {bx}, SELL {sx}; требуется немедленный preflight"
                out.append(o)
    return sorted(out,key=lambda x:x.net_edge_pct,reverse=True),signal_first_seen
