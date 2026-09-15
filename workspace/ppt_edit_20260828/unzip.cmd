@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0unzip_backend.ps1" -Mode "%~1" -ZipPath "%~2" -EntryName "%~3"
