
import json, time, threading, requests
from dataclasses import dataclass
from websocket import WebSocketApp

@dataclass
class LiveBBO:
    exchange: str
    asset: str
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    exchange_ts_ms: int
    recv_ts_ms: int

class LiveMarket:
    """
    Public market data only.
    Bybit/OKX/KuCoin use WebSocket.
    MEXC uses a compact 1-second REST fallback because the current MEXC
    book-ticker websocket is Protobuf-based.
    """
    def __init__(self, assets):
        self.assets=list(assets)
        self.lock=threading.RLock()
        self.data={}
        self.status={e:"STARTING" for e in ["Bybit","OKX","MEXC","KuCoin"]}
        self.stop_event=threading.Event()
        self.threads=[]

    def start(self):
        self.stop_event.clear()
        jobs=[self._bybit_loop,self._okx_loop,self._kucoin_loop,self._mexc_loop]
        for fn in jobs:
            t=threading.Thread(target=fn,daemon=True)
            t.start();self.threads.append(t)

    def stop(self):
        self.stop_event.set()

    def _put(self, exchange, asset, bid, ask, bid_qty=0.0, ask_qty=0.0, exchange_ts_ms=None):
        now=int(time.time()*1000)
        try:
            bid=float(bid);ask=float(ask);bid_qty=float(bid_qty or 0);ask_qty=float(ask_qty or 0)
            if bid<=0 or ask<=0:return
        except Exception:return
        q=LiveBBO(exchange,asset,bid,ask,bid_qty,ask_qty,int(exchange_ts_ms or now),now)
        with self.lock:
            self.data[(exchange,asset)]=q
            self.status[exchange]="LIVE"

    def snapshot(self):
        with self.lock:
            return dict(self.data),dict(self.status)

    def _run_ws_forever(self, exchange, url, on_open, on_message):
        while not self.stop_event.is_set():
            try:
                self.status[exchange]="CONNECTING"
                ws=WebSocketApp(url,on_open=on_open,on_message=on_message,
                    on_error=lambda w,e:self._set_status(exchange,f"ERR: {str(e)[:35]}"),
                    on_close=lambda w,c,m:self._set_status(exchange,"RECONNECT"))
                ws.run_forever(ping_interval=20,ping_timeout=8)
            except Exception as e:
                self._set_status(exchange,f"ERR: {str(e)[:35]}")
            if not self.stop_event.is_set():time.sleep(2)

    def _set_status(self,e,s):
        with self.lock:self.status[e]=s

    def _bybit_loop(self):
        def opened(ws):
            args=[f"tickers.{a}USDT" for a in self.assets]
            ws.send(json.dumps({"op":"subscribe","args":args}))
        def msg(ws, raw):
            try:
                j=json.loads(raw)
                topic=j.get("topic","")
                if not topic.startswith("tickers."):return
                a=topic.split(".",1)[1].replace("USDT","")
                d=j.get("data",{})
                self._put("Bybit",a,d.get("bid1Price"),d.get("ask1Price"),
                          d.get("bid1Size",0),d.get("ask1Size",0),j.get("ts"))
            except Exception:pass
        self._run_ws_forever("Bybit","wss://stream.bybit.com/v5/public/spot",opened,msg)

    def _okx_loop(self):
        def opened(ws):
            args=[{"channel":"bbo-tbt","instId":f"{a}-USDT"} for a in self.assets]
            ws.send(json.dumps({"op":"subscribe","args":args}))
        def msg(ws,raw):
            try:
                j=json.loads(raw);arg=j.get("arg",{})
                if arg.get("channel")!="bbo-tbt" or not j.get("data"):return
                a=arg["instId"].split("-")[0];d=j["data"][0]
                bids=d.get("bids",[]);asks=d.get("asks",[])
                if bids and asks:
                    self._put("OKX",a,bids[0][0],asks[0][0],bids[0][1],asks[0][1],d.get("ts"))
            except Exception:pass
        self._run_ws_forever("OKX","wss://ws.okx.com:8443/ws/v5/public",opened,msg)

    def _kucoin_loop(self):
        # Current public spot endpoint supports BBO ticker pushes around 100ms.
        def opened(ws):
            for a in self.assets:
                ws.send(json.dumps({"id":str(int(time.time()*1000)),"type":"subscribe",
                    "topic":f"/market/ticker:{a}-USDT","response":True}))
        def msg(ws,raw):
            try:
                j=json.loads(raw)
                if j.get("type")!="message":return
                topic=j.get("topic","")
                if not topic.startswith("/market/ticker:"):return
                a=topic.split(":",1)[1].split(",")[0].split("-")[0]
                d=j.get("data",{})
                self._put("KuCoin",a,d.get("bestBid"),d.get("bestAsk"),
                          d.get("bestBidSize",0),d.get("bestAskSize",0),
                          d.get("time") or d.get("Time"))
            except Exception:pass
        self._run_ws_forever("KuCoin","wss://ws-api-spot.kucoin.com",opened,msg)

    def _mexc_loop(self):
        s=requests.Session()
        while not self.stop_event.is_set():
            started=time.time()
            try:
                # One request for all book tickers is much lighter than N requests per asset.
                r=s.get("https://api.mexc.com/api/v3/ticker/bookTicker",timeout=4)
                r.raise_for_status()
                rows=r.json()
                if isinstance(rows,dict): rows=[rows]
                wanted={f"{a}USDT":a for a in self.assets}
                now=int(time.time()*1000)
                for d in rows:
                    sym=d.get("symbol")
                    if sym in wanted:
                        self._put("MEXC",wanted[sym],d.get("bidPrice"),d.get("askPrice"),
                                  d.get("bidQty",0),d.get("askQty",0),now)
                self._set_status("MEXC","LIVE/1s")
            except Exception as e:
                self._set_status("MEXC",f"ERR: {str(e)[:35]}")
            elapsed=time.time()-started
            self.stop_event.wait(max(0.05,1.0-elapsed))
