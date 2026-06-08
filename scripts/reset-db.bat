@echo off
cd /d %~dp0..
docker compose down -v
docker compose up -d
pause
