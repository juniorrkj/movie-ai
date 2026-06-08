@echo off
cd /d %~dp0..\python-ai
call .venv\Scripts\activate
python scrapers\seed_tmdb.py
pause
