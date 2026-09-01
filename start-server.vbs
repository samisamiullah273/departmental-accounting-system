Option Explicit

Dim shell, project, command
Set shell = CreateObject("WScript.Shell")
project = Replace(WScript.ScriptFullName, "start-server.vbs", "")
shell.CurrentDirectory = project
shell.Run "cmd /c for /f ""tokens=5"" %P in ('netstat -ano ^| findstr "":8000"" ^| findstr ""LISTENING""') do taskkill /PID %P /F >nul 2>&1", 0, True
command = "cmd /c python -m src.app > server.out.log 2> server.err.log"
shell.Run command, 0, False

Dim http, attempts
Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
For attempts = 1 To 20
    WScript.Sleep 500
    On Error Resume Next
    http.Open "GET", "http://127.0.0.1:8000/", False
    http.Send
    If Err.Number = 0 And http.Status = 200 Then Exit For
    Err.Clear
    On Error GoTo 0
Next
On Error GoTo 0
shell.Run "http://127.0.0.1:8000/", 1, False