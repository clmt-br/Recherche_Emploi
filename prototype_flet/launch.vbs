' Lance l'app en totale transparence : aucun flash de terminal.
' Double-clic sur ce fichier pour demarrer l'app.
' Alternative plus propre que launch.bat.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run "pythonw.exe app.py", 0, False
