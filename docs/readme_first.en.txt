OBS Navi {VERSION} test version: README

Thank you for helping test OBS Navi.
OBS Navi is a tool for operating OBS Studio with a screen reader (NVDA or PC-Talker).


== What is in this folder

There are 13 files and 2 folders. Japanese documents end in (Japanese), and English documents end in (English).

- OBSNavi.exe is the program. Start this file.
- README (English).txt is this file.
- Manual (English).html and Manual (English).txt explain how to use OBS Navi. They have the same content.
- Testing Guide (English).html and Testing Guide (English).txt describe what to check and how to report. They have the same content.
- README (Japanese).txt, Manual (Japanese).html and .txt, and Testing Guide (Japanese).html and .txt are the Japanese versions of the files above.
- LICENSE.txt is the full text of the license (GNU GPL version 3).
- THIRD-PARTY-NOTICES.txt lists the bundled components and their licenses.
- The _internal folder holds the parts OBS Navi needs to run. Do not change anything in it.
- The source folder holds the OBS Navi source code. You do not need it just to use OBS Navi.

The html documents can be navigated by headings in a browser, and the txt documents can be read from top to bottom in Notepad or similar.
When you start OBS Navi, a settings file named obs_navi_config.json is added to this folder.


== First three steps

1. Put this folder somewhere you can write to, such as Documents. Do not put it inside Program Files.
2. Start OBS Studio. In the Tools menu, open WebSocket Server Settings, check Enable WebSocket server, and press OK. Details are in "3. Setup and starting" in the Manual.
3. Start OBSNavi.exe. When it reads "OBS Navi version {VERSION} status" followed by "Connected to OBS", you are ready.

If a "Windows protected your PC" screen appears, press Tab to move to More info and press Enter, then press Tab to move to the Run anyway button and press Enter.


== Before testing

Export your OBS scene collection and profile. OBS Navi can delete scenes and sources, and deletion cannot be undone. The steps are in "2. Before testing" in the Testing Guide.

OBS Navi can start a stream. When you try streaming, do so in a way that is fine if viewers see it.


== Display language

OBS Navi starts in Japanese if the Windows display language is Japanese, and in English otherwise. To change it, choose the item named 表示の言語 (Language) in the Tools menu.


== Exiting

Press Alt+F4 to exit. Escape does not exit.


That is all.
