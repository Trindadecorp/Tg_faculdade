@echo off
REM Coleta incremental dos feeds de URL (OpenPhish + URLhaus).
REM Chamado pela tarefa agendada "PhishGuardBR-ColetaURL" a cada 12h.
REM Registrar/remover a tarefa: scripts\agendar_coleta.ps1

cd /d "%~dp0.."
"C:\Users\Pedro\AppData\Local\Programs\Python\Python312\python.exe" -u -m src.parsing.collect_url_feeds >> "data\raw\url_feeds\coleta.log" 2>&1
