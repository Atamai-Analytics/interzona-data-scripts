@echo off
rem Monthly refresh of interzona_cm (monthly_refresh.py --run). Run by the Windows scheduled task "Interzona-MonthlyRefresh" on the 6th at 08:30
rem (or at the next logon if the PC was off). The report goes to D:\CriticalMineralsDB\Documents\Monthly_Refresh; this log records each run.
rem Packages pip-installed from inside the Claude desktop app (MSIX) land in its virtualised AppData copy (LocalCache\Roaming),
rem which processes started by Task Scheduler cannot see; the real Roaming folder has only a few (no openpyxl). So both go on the path.
set PYTHONPATH=C:\Users\dean\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Python\Python314\site-packages;C:\Users\dean\AppData\Roaming\Python\Python314\site-packages
set PYTHONIOENCODING=utf-8
cd /d C:\Users\dean\claude_lithosurfer\lithosurfer-work\gold_schema
echo ===== %DATE% %TIME% >> D:\CriticalMineralsDB\Documents\Monthly_Refresh\monthly_refresh.log
C:\Python314\python.exe monthly_refresh.py --run >> D:\CriticalMineralsDB\Documents\Monthly_Refresh\monthly_refresh.log 2>&1
echo exit code %ERRORLEVEL% >> D:\CriticalMineralsDB\Documents\Monthly_Refresh\monthly_refresh.log
