Option Explicit
Dim shell, fso, folder, pythonw
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = shell.ExpandEnvironmentStrings("%LocalAppData%") & "\Programs\Python\Python312\pythonw.exe"
If Not fso.FileExists(pythonw) Then
  MsgBox "Khong tim thay Python 3.12. Hay mo Mo_ReelVoice.cmd de kiem tra.", 48, "Reel Voice"
  WScript.Quit 1
End If
shell.CurrentDirectory = folder
shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & folder & "\reel_voice.py" & Chr(34), 1, False
