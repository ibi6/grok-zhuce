@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 正在启动 Grok 注册机 GUI 界面...
python grok_register_ttk.py
pause
