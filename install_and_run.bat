@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo Arbitrage Radar v0.3
py -3.13 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
pause
