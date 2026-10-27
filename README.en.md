# OBS Navi

日本語: [README.md](README.md)

OBS Navi is a Windows tool for operating OBS Studio with a screen reader (NVDA or PC-Talker).

Many parts of the OBS Studio window are hard or impossible to read and operate with a screen reader. OBS Navi operates OBS from its own window, which is designed to work well with speech. It uses WebSocket, which comes built into OBS Studio. Keep OBS running and use OBS Navi alongside it. OBS Navi also announces changes made in OBS itself (for example, when streaming starts or the scene changes).

Everything can be done with the keyboard alone.

The window and speech are available in English and Japanese. OBS Navi follows the Windows display language (Japanese if Windows is in Japanese, otherwise English), and you can change it with the item named 表示の言語 (Language) in the Tools menu.

This is currently a test version.

## Made with AI

The source code and documents of OBS Navi were written with AI (Anthropic's Claude).

The author decides what to build, how it should work, and whether it is easy to use with speech. The author uses it with a screen reader and has fixed it while checking. Its behavior is also checked with automated tests (the tests folder).

## What it can do

- Start and stop streaming and recording, pause recording, add chapters (markers), save replays, and use the virtual camera
- Read the status (whether you are streaming or recording, and the current scene)
- Switch, create, configure, and delete scenes
- Show and hide sources; create, configure, and delete them; change their stacking order
- Game switch (point both the game video and the game audio to another game at once), video switch, and BGM playback
- Mute audio, change the volume (read in decibels), read levels (how loud the sound is right now), and set monitoring (whether you hear it yourself)
- Assign recording audio tracks (record the game audio, the screen reader voice, and the microphone on separate tracks)
- Add, configure, and delete audio filters (such as noise suppression)
- Check whether cameras are running, and enable or disable them
- Send screen reader voices to the stream or keep them out of it
- Warn about silence and clipping while streaming or recording, and about low disk space while recording
- Keys that work even while you are in a game (such as starting and stopping streaming and recording)
- English and Japanese display

## What it cannot do

- Install OBS or set up where you stream (Twitch, YouTube, and so on). Enter your stream key and similar settings in OBS itself
- Create a YouTube broadcast. Use Manage Broadcast in OBS itself
- Add video filters (such as chroma key). You can check, turn on or off, and delete video filters that already exist
- Change the scene order in OBS itself. You can change the order inside OBS Navi
- Choose where monitoring is heard (which headphones). Set that in OBS itself

## Requirements

- Windows 10 or Windows 11 (64-bit)
- OBS Studio 28 or later (the versions with WebSocket built in). Some features, such as chapters, do not work in older versions, so use a version that is as new as possible
- A screen reader: NVDA or PC-Talker
- No installation is needed, and no administrator rights are needed

## How to use

The full manual is [docs/manual.en.html](docs/manual.en.html). On GitHub it is shown as HTML source, so download it and open it in a browser. Each chapter has a heading, so you can move through it by headings.

The only thing you need to do first is enable the WebSocket server in OBS.

1. Start OBS Studio.
2. Press Alt+T to open the Tools menu, choose WebSocket Server Settings, and press Enter.
3. Check the Enable WebSocket server check box.
4. Make sure Enable Authentication is checked.
5. If Server Password is empty, press Generate Password.
6. Press OK to close.

You do not need to copy the password. OBS Navi reads the password and port from the OBS settings file by itself. If authentication is off, OBS Navi does not connect.

If the OBS settings window is hard to use with speech, you can also edit the settings file directly. The steps are in section 3.1 of the manual.

## Running from source

Tested with Windows 11 and Python 3.14 (64-bit). Run the commands in this folder.

1. Install the components.

   ```
   python -m pip install wxPython==4.2.5 obsws-python==1.8.0 websocket-client==1.9.0 accessible_output2==0.17
   ```

2. Start OBS Navi.

   ```
   python -X utf8 app.py
   ```

   To start it in a specific language regardless of the settings, set the environment variable OBSNAVI_LANG to en or ja first.

3. Run the tests (OBS is not needed). The tests run in Japanese.

   ```
   python -X utf8 tests\run_tests.py
   ```

   A separate check builds the window in English and makes sure no Japanese text is left.

   ```
   python -X utf8 tests\en_probe.py
   ```

## Building the program file

1. Install PyInstaller.

   ```
   python -m pip install pyinstaller==6.20.0
   ```

2. Exit OBS Navi, then run the following. If it is running, the build may be missing the DLLs used for speech.

   ```
   python -X utf8 -m PyInstaller --noconfirm obs_navi.spec
   ```

3. dist\OBSNavi\OBSNavi.exe is created.

The release zip is built with `python -X utf8 tools\build_release.py`.

## What is in this folder

- app.py is the entry point
- version.py holds the version number
- speech.py sends speech to the screen reader
- The core folder handles communication with OBS and the processing that does not depend on the window. The keys are defined in core\keymap.py, and the display language is decided in core\i18n.py
- The ui folder is the window (wxPython)
- The tests folder holds the tests
- The tools folder generates and checks the documents and builds the release package
- The docs folder holds the source HTML of the manual and the testing guide (manual.en.html and tester.en.html are the English versions)
- obs_navi.spec is the build setting for the program file (PyInstaller)

## License

Copyright (C) 2026 Takahashi

OBS Navi is distributed under the GNU General Public License version 3 (GPL-3.0). The full text is in [LICENSE.txt](LICENSE.txt). You are free to use, share, and modify it. When you share it, use the same license and include the source code. It comes with no warranty.

OBS Navi uses obsws-python, which is GPL-3.0, so OBS Navi is GPL-3.0 as well.
