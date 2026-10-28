@echo off
setlocal
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
python -c "from pathlib import Path; import secrets; p=Path('.env'); s=p.read_text(); p.write_text(s.replace('replace-with-a-long-random-secret', secrets.token_hex(32)))"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
