
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

class RadarDB:
    def __init__(self,path):
        self.path=path; Path(path).parent.mkdir(parents=True,exist_ok=True); self._init()
    def con(self):
        c=sqlite3.connect(self.path,timeout=15); c.execute("PRAGMA journal_mode=WAL"); return c
    def _init(self):
        with self.con() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS opportunities(
              id INTEGER PRIMARY KEY, ts TEXT, asset TEXT, long_exchange TEXT, short_exchange TEXT,
              gross_apr_pct REAL, gross_spread_per_hour REAL, est_total_cost REAL,
              break_even_hours REAL, entry_price_gap_pct REAL);
            CREATE INDEX IF NOT EXISTS idx_ops ON opportunities(asset,long_exchange,short_exchange,ts);
            CREATE TABLE IF NOT EXISTS basis(
              id INTEGER PRIMARY KEY, ts TEXT, exchange TEXT, asset TEXT, basis_pct REAL,
              funding_apr_pct REAL, est_total_cost REAL, simple_net_basis_pct REAL);
            CREATE TABLE IF NOT EXISTS classic_arbitrage(
              id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, asset TEXT,
              buy_exchange TEXT, sell_exchange TEXT, buy_ask REAL, sell_bid REAL,
              gross_spread_pct REAL, est_total_cost REAL, net_edge_pct REAL);
            CREATE INDEX IF NOT EXISTS idx_classic ON classic_arbitrage(asset,buy_exchange,sell_exchange,ts);
            CREATE TABLE IF NOT EXISTS paper_trades(
              id INTEGER PRIMARY KEY AUTOINCREMENT, opened_ts TEXT, closed_ts TEXT,
              asset TEXT, long_exchange TEXT, short_exchange TEXT, capital REAL,
              entry_apr REAL, entry_cost REAL, status TEXT DEFAULT 'OPEN', realized_pnl REAL DEFAULT 0);
            """)
    def save(self,ops,basis,classic=None):
        with self.con() as c:
            for o in ops:
                c.execute("INSERT INTO opportunities(ts,asset,long_exchange,short_exchange,gross_apr_pct,gross_spread_per_hour,est_total_cost,break_even_hours,entry_price_gap_pct) VALUES(?,?,?,?,?,?,?,?,?)",
                  (o.ts,o.asset,o.long_exchange,o.short_exchange,o.gross_apr_pct,o.gross_spread_per_hour,o.est_total_cost,o.break_even_hours,o.entry_price_gap_pct))
            for b in basis:
                c.execute("INSERT INTO basis(ts,exchange,asset,basis_pct,funding_apr_pct,est_total_cost,simple_net_basis_pct) VALUES(?,?,?,?,?,?,?)",
                  (b.ts,b.exchange,b.asset,b.basis_pct,b.funding_apr_pct,b.est_total_cost,b.simple_net_basis_pct))
            for a in (classic or []):
                c.execute("INSERT INTO classic_arbitrage(ts,asset,buy_exchange,sell_exchange,buy_ask,sell_bid,gross_spread_pct,est_total_cost,net_edge_pct) VALUES(?,?,?,?,?,?,?,?,?)",
                  (a.ts,a.asset,a.buy_exchange,a.sell_exchange,a.buy_ask,a.sell_bid,a.gross_spread_pct,a.est_total_cost,a.net_edge_pct))
    def history(self,a,l,s,limit=1000):
        with self.con() as c:
            x=c.execute("SELECT ts,gross_apr_pct,break_even_hours FROM opportunities WHERE asset=? AND long_exchange=? AND short_exchange=? ORDER BY id DESC LIMIT ?",(a,l,s,limit)).fetchall()
        return list(reversed(x))
    def stats(self,a,l,s,limit=1000):
        x=self.history(a,l,s,limit)
        if not x:return {}
        v=[r[1] for r in x]
        return {"samples":len(v),"avg_apr":sum(v)/len(v),"min_apr":min(v),"max_apr":max(v),
                "above_10_pct":sum(z>=10 for z in v)/len(v)*100,"above_20_pct":sum(z>=20 for z in v)/len(v)*100}
    def open_paper(self,o,capital):
        with self.con() as c:
            c.execute("INSERT INTO paper_trades(opened_ts,asset,long_exchange,short_exchange,capital,entry_apr,entry_cost) VALUES(?,?,?,?,?,?,?)",
              (datetime.now(timezone.utc).isoformat(timespec="seconds"),o.asset,o.long_exchange,o.short_exchange,capital,o.gross_apr_pct,o.est_total_cost))
    def paper_rows(self):
        with self.con() as c:
            return c.execute("SELECT id,opened_ts,asset,long_exchange,short_exchange,capital,entry_apr,status,realized_pnl FROM paper_trades ORDER BY id DESC").fetchall()
