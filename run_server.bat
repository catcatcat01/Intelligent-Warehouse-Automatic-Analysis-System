@echo off
echo Starting Waitress Server...
waitress-serve --listen=10.60.208.29:8080 app2:app
pause
