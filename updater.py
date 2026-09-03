
from pathlib import Path
import json, urllib.request, tempfile, zipfile, shutil, subprocess, sys, time, hashlib, os

PRESERVE_NAMES={"data","settings.json","__pycache__",".venv"}

def parse_version(v):
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("v").split("."))
    except Exception:
        return (0,)

def current_version(app_dir=None):
    app_dir=Path(app_dir or Path(__file__).resolve().parent)
    p=app_dir/"version.json"
    if not p.exists(): return "0.0.0"
    try:return json.loads(p.read_text(encoding="utf-8")).get("version","0.0.0")
    except Exception:return "0.0.0"

def fetch_manifest(url, timeout=10):
    req=urllib.request.Request(url,headers={"User-Agent":"ArbitrageRadar-Updater"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def download(url,dest,timeout=60):
    req=urllib.request.Request(url,headers={"User-Agent":"ArbitrageRadar-Updater"})
    with urllib.request.urlopen(req,timeout=timeout) as r, open(dest,"wb") as f:
        shutil.copyfileobj(r,f)
    return Path(dest)

def sha256_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest().lower()

def verify_sha256(path, expected):
    if not expected:
        raise RuntimeError("В манифесте обновления отсутствует sha256.")
    actual=sha256_file(path)
    if actual != expected.strip().lower():
        raise RuntimeError(f"SHA-256 не совпадает.\nОжидался: {expected}\nПолучен: {actual}")
    return True

def inspect_zip(zip_path):
    with zipfile.ZipFile(zip_path,"r") as z:
        names=z.namelist()
        if "version.json" in names:return ""
        roots={n.split("/",1)[0] for n in names if "/" in n}
        for root in roots:
            if f"{root}/version.json" in names:return root
    raise RuntimeError("Это не пакет Arbitrage Radar: version.json не найден.")

def _worker_script():
    return r"""
import sys,time,zipfile,shutil,subprocess,os
from pathlib import Path
zip_path=Path(sys.argv[1]);app_dir=Path(sys.argv[2]);root=sys.argv[3]
time.sleep(2)
tmp=Path(str(zip_path)+".extract")
if tmp.exists():shutil.rmtree(tmp,ignore_errors=True)
tmp.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(zip_path,"r") as z:z.extractall(tmp)
src=tmp/root if root else tmp
backup=app_dir.parent/(app_dir.name+"_backup_before_update")
if backup.exists():shutil.rmtree(backup,ignore_errors=True)
backup.mkdir(parents=True,exist_ok=True)
preserve={"data","settings.json","__pycache__",".venv"}
try:
    for p in app_dir.iterdir():
        if p.name not in preserve:
            dest=backup/p.name
            if p.is_dir():shutil.copytree(p,dest)
            else:shutil.copy2(p,dest)
    for p in src.iterdir():
        if p.name in preserve:continue
        dest=app_dir/p.name
        if p.is_dir():
            if dest.exists():shutil.rmtree(dest,ignore_errors=True)
            shutil.copytree(p,dest)
        else:
            shutil.copy2(p,dest)
    run=app_dir/"run.bat"
    if run.exists():subprocess.Popen(["cmd","/c",str(run)],cwd=str(app_dir))
except Exception:
    # best-effort rollback
    for p in backup.iterdir():
        dest=app_dir/p.name
        if p.is_dir():
            if dest.exists():shutil.rmtree(dest,ignore_errors=True)
            shutil.copytree(p,dest)
        else:shutil.copy2(p,dest)
    raise
finally:
    shutil.rmtree(tmp,ignore_errors=True)
"""

def stage_update(zip_path, app_dir):
    zip_path=Path(zip_path);app_dir=Path(app_dir)
    root=inspect_zip(zip_path)
    worker=Path(tempfile.gettempdir())/"arbitrage_radar_update_worker.py"
    worker.write_text(_worker_script(),encoding="utf-8")
    subprocess.Popen([sys.executable,str(worker),str(zip_path),str(app_dir),root],
                     cwd=str(app_dir),creationflags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0))
