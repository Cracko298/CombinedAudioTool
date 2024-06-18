# CombinedAudioTool
- A Tool for CombinedAudio.bin for Minecraft for New Nintendo 3DS Edition (MC3DS) with a plethora of Features.
- Only support Windows Platforms Officially, due to being built and made using some Windows API functions.

## Feature Set:
- Extract All FSB Soundbank Files in the Archive.
- Extract a FSB Soundbank File by Name/Sound-ID.
- Get File name(s) from Soundbank Files for easier recognition.
- Rename Extracted files to original filename(s).
- Rebuild `CombinedAudio.bin` with new Custom Audio Files.
- Extract Header from `CombinedAudio.bin`.
- Add padding to files automatically (Requires Original Extracted File).

## Downlaod(s):
- Download [Here](https://github.com/Minecraft-3DS-Community/CombinedAudioTool/releases/download/v1.1.0/CATool.py).
- Requires `Python 3.8+` and `Python STD` (Installed alongside Python).
## Usage:
```
python CATool.py
       --eca,  extract-ca     [CombinedAudioPATH]                            > Extracts All FSB Soundbank Files from the CombinedAudio.bin Archive.
       --fn,   find-sn        [SegmentFilePATH]                              > Find the Segment Name from an Extracted FSB Soundbank File via --eca Flag.
       --rs,   rename-s       [SegmentFilePATH]                              > Rename a Segment File FSB Soundbank File back to it's Original Filename.
       --gh,   get-header     [CombinedAudioPATH]                            > Extracts the Header from the CombinedAudio.bin Archive.
       --rca,  rebuild-ca     [SegmentOutFolderPATH]                         > Rebuilds the CombinedAudio.bin Archive via Segment Files.
       --ap,   add-padding    [OriginalFilePATH]       [ModifiedFilePATH]    > Adds padding to set the Modified File Equal to the Original File Size.
       --ne,   name-extract   [CombinedAudioPATH]      [Sound Name/ID]       > Extracts a FSB Soundbank File from the CombinedAudio.bin Archive via Name/SoundID.
       --ra,   rename-all     [SegmentFolderPATH]                            > Renames all Segment Files back to their original FSB Soundbank Filename(s).
       --gsid, get-soundid    [CombinedAudioPATH]                            > Gets all Sound Names/ID's and Dumps them to a *.txt File.
       --h,    help                                                          > Displays this Message.
```
### Help Message:
```
python CATool.py --h
```
