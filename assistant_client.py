
import os
try: import keyring
except: keyring=None
SERVICE="ArbitrageRadar"; USERNAME="openai_api_key"
def save_api_key(v):
    v=v.strip()
    if not v:return False
    if keyring:keyring.set_password(SERVICE,USERNAME,v)
    else:os.environ["OPENAI_API_KEY"]=v
    return True
def get_api_key():
    if keyring:
        try:
            v=keyring.get_password(SERVICE,USERNAME)
            if v:return v
        except:pass
    return os.environ.get("OPENAI_API_KEY")
def ask_openai(q,ctx,model):
    from openai import OpenAI
    key=get_api_key()
    if not key: raise RuntimeError("OpenAI API key не задан. Откройте Настройки → OpenAI API.")
    client=OpenAI(api_key=key)
    r=client.responses.create(model=model,instructions="Ты аналитический ассистент Arbitrage Radar. Отвечай по-русски. Опирайся только на переданные данные. Gross APR не называй ожидаемой доходностью. Всегда учитывай расходы и устойчивость spread. NO TRADE — нормальный вывод.",input=f"КОНТЕКСТ:\n{ctx}\n\nВОПРОС:\n{q}")
    return r.output_text
