@echo off
rem Sunshine "prep commands" for the Couch app (see docs\streaming-setup.md):
rem   Do:   stream.cmd on "Apple TV"   - a Moonlight stream started: Couch shows it, opens the launcher, leaves audio alone
rem   Undo: stream.cmd off             - the stream ended
rem Always exits 0, so Sunshine never aborts a stream because Couch isn't running. Port 8765 = config.json "port".
set "CURL=%SystemRoot%\System32\curl.exe"
set "API=http://127.0.0.1:8765/api"
if /i "%~1"=="on" goto on
"%CURL%" -s -m 5 -o NUL -X POST -H "X-Couch: 1" -H "Content-Type: application/json" -d "{\"on\":false}" "%API%/stream"
exit /b 0
:on
"%CURL%" -s -m 5 -o NUL -X POST -H "X-Couch: 1" -H "Content-Type: application/json" -d "{\"on\":true,\"device\":\"%~2\"}" "%API%/stream"
"%CURL%" -s -m 5 -o NUL -X POST -H "X-Couch: 1" -H "Content-Type: application/json" -d "{\"action\":\"launcher\"}" "%API%/window"
exit /b 0
