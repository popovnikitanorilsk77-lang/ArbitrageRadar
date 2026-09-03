
import os,time,hmac,hashlib,base64,json,requests,urllib.parse
try:
    import keyring
except Exception:
    keyring=None

SERVICE="ArbitrageRadar.Exchange"
FIELDS={
    "Bybit":["api_key","secret"],
    "OKX":["api_key","secret","passphrase"],
    "MEXC":["api_key","secret"],
    "KuCoin":["api_key","secret","passphrase"],
}

def _name(exchange,field): return f"{exchange}:{field}"

def save_credentials(exchange, values):
    if not keyring: raise RuntimeError("keyring недоступен")
    for field in FIELDS[exchange]:
        val=(values.get(field) or "").strip()
        if val:keyring.set_password(SERVICE,_name(exchange,field),val)

def get_credentials(exchange):
    out={}
    if not keyring:return out
    for field in FIELDS[exchange]:
        try:
            v=keyring.get_password(SERVICE,_name(exchange,field))
            if v:out[field]=v
        except Exception:pass
    return out

def credentials_present(exchange):
    c=get_credentials(exchange)
    return all(c.get(x) for x in FIELDS[exchange])

def _bybit_balance(c):
    ts=str(int(time.time()*1000));recv="5000";query="accountType=UNIFIED"
    sign=hmac.new(c["secret"].encode(),(ts+c["api_key"]+recv+query).encode(),hashlib.sha256).hexdigest()
    h={"X-BAPI-API-KEY":c["api_key"],"X-BAPI-TIMESTAMP":ts,"X-BAPI-RECV-WINDOW":recv,"X-BAPI-SIGN":sign}
    j=requests.get("https://api.bybit.com/v5/account/wallet-balance?"+query,headers=h,timeout=8).json()
    if str(j.get("retCode"))!="0":raise RuntimeError(j.get("retMsg") or str(j))
    coins=[]
    for acc in j["result"]["list"]:
        for x in acc.get("coin",[]):
            try:
                eq=float(x.get("equity") or 0)
                if abs(eq)>0:coins.append((x["coin"],eq,float(x.get("walletBalance") or 0)))
            except:pass
    return coins

def _okx_balance(c):
    ts=time.strftime("%Y-%m-%dT%H:%M:%S",time.gmtime())+f".{int(time.time()*1000)%1000:03d}Z"
    path="/api/v5/account/balance";pre=ts+"GET"+path
    sign=base64.b64encode(hmac.new(c["secret"].encode(),pre.encode(),hashlib.sha256).digest()).decode()
    h={"OK-ACCESS-KEY":c["api_key"],"OK-ACCESS-SIGN":sign,"OK-ACCESS-TIMESTAMP":ts,"OK-ACCESS-PASSPHRASE":c["passphrase"]}
    j=requests.get("https://www.okx.com"+path,headers=h,timeout=8).json()
    if str(j.get("code"))!="0":raise RuntimeError(j.get("msg") or str(j))
    coins=[]
    for acc in j.get("data",[]):
        for x in acc.get("details",[]):
            try:
                eq=float(x.get("eq") or x.get("cashBal") or 0)
                if abs(eq)>0:coins.append((x["ccy"],eq,float(x.get("availBal") or 0)))
            except:pass
    return coins

def _mexc_balance(c):
    ts=str(int(time.time()*1000));query=f"timestamp={ts}"
    sig=hmac.new(c["secret"].encode(),query.encode(),hashlib.sha256).hexdigest()
    h={"X-MEXC-APIKEY":c["api_key"]}
    j=requests.get("https://api.mexc.com/api/v3/account?"+query+"&signature="+sig,headers=h,timeout=8).json()
    if "code" in j and j.get("code") not in (0,200):raise RuntimeError(j.get("msg") or str(j))
    coins=[]
    for x in j.get("balances",[]):
        try:
            free=float(x.get("free") or 0);locked=float(x.get("locked") or 0)
            if free or locked:coins.append((x["asset"],free+locked,free))
        except:pass
    return coins

def _kucoin_balance(c):
    ts=str(int(time.time()*1000));path="/api/v1/accounts";pre=ts+"GET"+path
    sign=base64.b64encode(hmac.new(c["secret"].encode(),pre.encode(),hashlib.sha256).digest()).decode()
    pp=base64.b64encode(hmac.new(c["secret"].encode(),c["passphrase"].encode(),hashlib.sha256).digest()).decode()
    h={"KC-API-KEY":c["api_key"],"KC-API-SIGN":sign,"KC-API-TIMESTAMP":ts,
       "KC-API-PASSPHRASE":pp,"KC-API-KEY-VERSION":"2"}
    j=requests.get("https://api.kucoin.com"+path,headers=h,timeout=8).json()
    if str(j.get("code"))!="200000":raise RuntimeError(j.get("msg") or str(j))
    coins=[]
    for x in j.get("data",[]):
        try:
            bal=float(x.get("balance") or 0);avail=float(x.get("available") or 0)
            if bal:coins.append((x["currency"],bal,avail))
        except:pass
    return coins

LOADERS={"Bybit":_bybit_balance,"OKX":_okx_balance,"MEXC":_mexc_balance,"KuCoin":_kucoin_balance}

def load_balance(exchange):
    c=get_credentials(exchange)
    missing=[x for x in FIELDS[exchange] if not c.get(x)]
    if missing:raise RuntimeError("API-данные не заполнены")
    return LOADERS[exchange](c)
