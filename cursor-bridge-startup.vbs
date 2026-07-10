' Cursor Bridge - startup VBS wrapper (no console flash)
' Place this file next to cursor_bridge.pyw, then copy a shortcut to:
'   wscript.exe "FULL_PATH\cursor-bridge-startup.vbs"
' into your Startup folder:
'   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
' IMPORTANT: save this file as ANSI/ASCII, NOT UTF-8 (VBScript does not support UTF-8)

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

Set objShell = CreateObject("WScript.Shell")
objShell.Run "pythonw.exe """ & scriptDir & "\cursor_bridge.pyw""", 0, False
