tell application "Terminal"
    -- Launch the Python Backend
    do script "cd '/Volumes/Macintosh HD/Users/jounxu/Documents/program project/date tuomin/legal-redaction/backend' && pkill -f 'uvicorn app.main' || true && source ~/.zshrc 2>/dev/null || true && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
    
    -- Launch the Vite Frontend in a new tab
    do script "cd '/Volumes/Macintosh HD/Users/jounxu/Documents/program project/date tuomin/legal-redaction/frontend' && source ~/.zshrc 2>/dev/null || true && npx vite --host 0.0.0.0 --port 5173"
end tell

-- Wait a few seconds for servers to start
delay 4

-- Open the browser automatically
tell application "Safari"
    open location "http://127.0.0.1:5173"
end tell
