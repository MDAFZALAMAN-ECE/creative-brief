@echo off
setlocal
cd /d "%~dp0frontend"
if not exist node_modules (
  npm install
)
if not exist .env.local copy .env.example .env.local
npm run dev
