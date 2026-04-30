# CombinedAudioTool
- A Tool (GUI/CLI) for CombinedAudio.bin for Minecraft for New Nintendo 3DS Edition (MC3DS) with a plethora of Features.
- Only support Windows Platforms Officially, due to being built and made using some Windows API functions (`winsound`).
- View the Documentation of `CombinedAudio.bin` [Here](https://github.com/Cracko298/CombinedAudioTool/blob/main/COMBINED_ADUIO_HEADER_TOC.md).

## Feature Set:
- Extract All FSB SoundBank Files from `CombinedAudio.bin`.
- Play, Pause, Seek, Restart, Search through Audio Tracks.
- Gain information about metadata, the Archive itself, and more.
- Convert between formats, including `*.wav`, `*.dsp`, `*.fsb`, and many more.
- Convert Songs, Add SFX, and Extract Segments/Header information.

## Download(s):
- Download [Here](https://github.com/Minecraft-3DS-Community/CombinedAudioTool/releases/download/v2.7.1/CATool.exe).
- Requires `Python 3.12+` and `Python STD` (Installed alongside Python).

## Building:
- We package it using PyInstaller.
```
py -3.14 -m PyInstaller --onefile --windowed --name CATool --icon icon.ico --add-binary "catool_fast.cp314-win_amd64.pyd;." --add-data "icon.ico;." CATool.py
```
