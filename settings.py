
import json
from pathlib import Path

DEFAULTS={
    "assets":["BTC","ETH","SOL","XRP","DOGE"],
    "exchanges":["Bybit","OKX","MEXC","KuCoin"],
    "refresh_seconds":60,
    "live_ui_ms":250,
    "capital":5000.0,
    "hold_hours":24.0,
    "min_gross_apr_pct":20.0,
    "max_break_even_hours":72.0,
    "slippage_total":0.0004,
    "taker_fees":{"Bybit":0.0006,"OKX":0.0006,"MEXC":0.0006,"KuCoin":0.0006},
    "openai_model":"gpt-5",
    "update_manifest_url":"https://raw.githubusercontent.com/popovnikitanorilsk77-lang/ArbitrageRadar/main/update.json",
    "classic_min_net_edge_pct":0.10,
    "classic_strong_net_edge_pct":0.25,
    "max_quote_age_ms":1500,
    "live_execution_enabled":False
}
class SettingsStore:
    def __init__(self,path):
        self.path=Path(path); self.load()
    def load(self):
        self.data=dict(DEFAULTS)
        self.data["taker_fees"]=dict(DEFAULTS["taker_fees"])
        if self.path.exists():
            try:
                d=json.loads(self.path.read_text(encoding="utf-8"))
                for k,v in d.items():
                    if k=="taker_fees": self.data[k].update(v)
                    else:self.data[k]=v
            except Exception:
                pass
    def get(self,k,d=None): return self.data.get(k,d)
    def set(self,k,v):
        self.data[k]=v
        self.path.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding="utf-8")
