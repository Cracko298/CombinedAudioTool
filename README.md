# CombinedAudioTool
- A Tool (GUI/CLI) for CombinedAudio.bin for Minecraft for New Nintendo 3DS Edition (MC3DS) with a plethora of Features.
- Only support Windows Platforms Officially, due to being built and made using some Windows API functions (`winsound`).

## Feature Set:
- Extract All FSB SoundBank Files from `CombinedAudio.bin`.
- Play, Pause, Seek, Restart, Search through Audio Tracks.
- Gain information about metadata, the Archive itself, and more.
- Convert between formats, including `*.wav`, `*.dsp`, `*.fsb`.
- Convert Songs, Add SFX, and Extract Segments/Header information.

## Download(s):
- Download [Here](https://github.com/Minecraft-3DS-Community/CombinedAudioTool/releases/download/v2.6/CATool.exe).
- Requires `Python 3.12+` and `Python STD` (Installed alongside Python).

## Building:
- We package it using PyInstaller.
```
py -m PyInstaller --onefile --windowed --icon=icon.ico --add-data "icon.ico;." ".\CATool.py"
```
