import os, sys, re, urllib.request, time, zipfile, io, winsound, shutil
from tkinter import messagebox
VERSION = 2.1

try:
    import requests
except ImportError:
    os.system('pip install requests')
    print("\n\nInstalled 'requests' Module.\nPlease Retry your Command.")
    sys.exit(1)

def restoreToolInt():
    file_name = 'CATool'
    release_url = f"https://api.github.com/repos/Minecraft-3DS-Community/CombinedAudioTool/releases/tag/v{VERSION}"
    response = requests.get(release_url)
    release_info = response.json()
    print(f"\nGetting Your Version (v{VERSION}) of CATool...")
    asset_url = None
    for asset in release_info['assets']:
        if asset['name'] == f"{file_name}.py" or asset['name'] == f"{file_name}.zip":
            asset_url = asset['browser_download_url']
            print(f"Most Recent Version: {asset_url}")
            break
    else:
        raise ValueError(f"No asset named '{file_name}' or .zip file found in the latest release.")

    response = requests.get(asset_url)
    if asset['name'] == f"{file_name}.zip":
        print("Downloading and extracting the latest CATool.zip...")
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            z.extractall('.')
        print("Extracted the contents of the latest CATool.zip")
    else:
        print("Downloading CATool...")
        with open(file_name, 'wb') as f:
            f.write(response.content)
        print("Downloaded the latest CATool")

try:
    from extrcd import fsb5
except ImportError:
    print(f"The Tool experienced an Unhandeled Exception.\nTool Directory: '.\\extrcd' has not been Found.")
    restore = sys.argv[1]
    if restore == 'restore' or restore == '--rstr':
        restoreToolInt()
    print(f"Use the Restore Flag to Restore the File ")

def extrCombAudio():
    def find_segments(file_path):
        with open(file_path, 'rb') as f:
            data = f.read()

        segments = []
        start_idx = 0
        while True:
            fsb5_start = data.find(b'FSB5', start_idx)
            if fsb5_start == -1:
                break

            fsb5_end = data.find(b'FSB5', fsb5_start + 4)
            if fsb5_end == -1:
                fsb5_end = len(data)

            segments.append(data[fsb5_start:fsb5_end])
            start_idx = fsb5_end
        return segments

    def save_segments(segments):
        os.makedirs('.\\out_path', exist_ok=True)
        for i, segment in enumerate(segments):
            with open(f'.\\out_path\\segment_{i}.fsb', 'wb') as f:
                f.write(segment)

    file_path = sys.argv[2]
    file_path = file_path.replace("\\",'/')
    segments = find_segments(file_path)
    save_segments(segments)

def find_segment_name():
    file_path = sys.argv[2]
    search_pattern = b'\x00\x04\x00\x00\x00'
    max_search_length = 0xFF

    try:
        with open(file_path, 'rb') as f:
            segment = f.read(max_search_length)
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return None
    except IOError as e:
        print(f"Error reading file: {e}")
        return None

    pattern_start = segment.find(search_pattern)
    if pattern_start == -1:
        print("Pattern not found")
        return None

    string_start = pattern_start + len(search_pattern)
    string_end = string_start
    while string_end < len(segment) and segment[string_end] != 0x00:
        string_end += 1

    segment_name = segment[string_start:string_end].decode('utf-8')
    return segment_name

def rename_segment():
    segment_file = sys.argv[2]
    segment_name1 = find_segment_name()
    seg_dir = os.path.dirname(segment_file)
    os.rename(segment_file,f"{seg_dir}\\{segment_name1}.fsb")

def collect_header():
    audio_file = sys.argv[2]
    os.makedirs('.\\out_path', exist_ok=True)
    with open(audio_file,'rb+') as f:
        data = f.read(0x1A2C)
        with open(f".\\out_path\\header_data.bin",'wb') as of:
            of.write(data)

def rebCombAudio():
    audio_files = sys.argv[2]
    header = f"{audio_files}\\header_data.bin"
    if os.path.exists(header) != True:
        print(f"Please Extract the Header from your CombinedAudio.bin File.")
        sys.exit(1)
    if os.path.exists(f"{audio_files}\\segment_0.fsb") != True:
        print(f"This Function Requires that the Audio Files are Named into the following scheme:\n 'segment_XXX.fsb' nothing else.")
        sys.exit(1)
    
    with open(header,'rb+') as header_file:
        header_data = header_file.read()
    
    with open('.\\ModifiedCombinedAudio.bin','wb+') as f:
        f.write(header_data)
        for i in range(558):
            with open(f"{audio_files}\\segment_{i}.fsb",'rb+') as sf:
                fsb_data = sf.read()
                f.write(fsb_data)

def extractByName():
    audio_path = sys.argv[2]
    search_text = sys.argv[3]
    search_text = search_text.lower()
    file_names = os.path.basename(audio_path)
    directory_name = os.path.dirname(__file__)

    with open(audio_path, 'rb') as file:
        content = file.read()

    search_text_bytes = search_text.encode('utf-8')
    fsb_magic = b'FSB5'
    search_text_index = -1

    while True:
        search_text_index = content.find(search_text_bytes, search_text_index + 1)
        if search_text_index == -1:
            print(f"\nSearch text '{search_text}' not found surrounded by null bytes in file.\nDid you mistype the Sound-ID?")
            sys.exit(1)

        if content[search_text_index - 1] == 0x00 and content[search_text_index + len(search_text_bytes)] == 0x00:
            break

    closest_fsb_index = content.rfind(fsb_magic, 0, search_text_index)
    if closest_fsb_index == -1:
        print("\nFSB5 Magic String not found before the search text.\nAre you sure this is a Soundbank FSB Archive?\n")
        sys.exit(1)

    next_fsb_index = content.find(fsb_magic, closest_fsb_index + len(fsb_magic))
    if next_fsb_index == -1:
        next_fsb_index = len(content)

    extracted_data = content[closest_fsb_index:next_fsb_index]

    output_path = os.path.join(directory_name, f'{search_text}.fsb')
    with open(output_path, 'wb') as output_file:
        output_file.write(extracted_data)

    print(f"\nExtracted Soundbank FSB From '{file_names}' Archive.\nTo Output PATH: '{output_path}'.\n")

def addPadding():
    originalFile = sys.argv[2]
    modifiedFile = sys.argv[3]
    with open(originalFile, 'rb') as f:
        originalData = f.read()
        ogDataLen = len(originalData)

        with open(modifiedFile,'rb') as mf:
            modifiedData = mf.read()
            modDataLen = len(modifiedData)
            mf.close()

        difference = ogDataLen-modDataLen
        with open(modifiedFile,'ab') as of:
            for i in range(difference):
                of.write(b'\x00')
        
        with open(modifiedFile,'rb+') as newestF:
            newestF.seek(0x14)
            sampleSize = newestF.read(0x04)
            sampleNumber = int.from_bytes(sampleSize,byteorder='little')
            newSize = sampleNumber+difference
            newestF.seek(0x14)
            newSize = newSize.to_bytes(4, byteorder='little')
            newestF.write(newSize)

def formatsToWave():
    if os.path.exists(f"{os.path.dirname(__file__)}\\extrcd\\mpg\\bin") != True:
        print("\n\nFFMPEG Has NOT been installed.\nPlease install with: '--impg' Flag.\n")
        sys.exit(1)
    fileToConvert = sys.argv[2]
    if '.ogg' in fileToConvert:
        newFile = fileToConvert.replace('.ogg','.wav')
        newFile = os.path.basename(newFile)
        os.system(f'.\\extrcd\\mpg\\bin\\ffmpeg.exe -y -loglevel quiet -i {fileToConvert} {os.path.dirname(__file__)}\\{newFile}')
    if '.mp3' in fileToConvert:
        newFile = fileToConvert.replace('.mp3','.wav')
        newFile = os.path.basename(newFile)
        os.system(f'.\\extrcd\\mpg\\bin\\ffmpeg.exe -y -loglevel quiet -i {fileToConvert} {os.path.dirname(__file__)}\\{newFile}')
    if '.flv' in fileToConvert:
        newFile = fileToConvert.replace('.flv','.wav')
        newFile = os.path.basename(newFile)
        os.system(f'.\\extrcd\\mpg\\bin\\ffmpeg.exe -y -loglevel quiet -i {fileToConvert} {os.path.dirname(__file__)}\\{newFile}')

    print("\n\nConversion Completed.\n")


def info_help():
    print(f"""\n
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
       --gssg, get-size-seg   [SegmentFilePATH]                              > Gets the size of a specific Segment Soundbank FSB File.
       --gs,   get-size       [SegmentOutFolderPATH]                         > Gets the size of all Segment Soundbank FSB Files.
       --exa,  extract-seg    [SegmentFilePATH]                              > Attempts to extract Audio from Segment Soundbank FSB Files.
       --cwav, convert-wave   [SegmentFilePATH]        [FileToConvertPATH]   > Convert Custom Audio to Nintendo 'GCADPCM'/'DSADPCM' Format.
       --pa,   play-audio     [WaveFilePATH]                                 > Play Audio from a Wave-File.
       --gmsc, generate-music [WaveFilePATH]                                 > Generates a Valid Music FSB Soundbank File for Minecraft 3DS Edition from a Wave File.
       --atw,  to-wave        [AudioFileToConvertToWavPATH]                  > Convert basically any Audio format like *.fsb, *.dsp or Formats like *.mp3 to Wave Format.
       --impg, inst-ffmpeg                                                   > Install FFMPEG to '{os.path.dirname(__file__)}\\extrcd\\mpg\\bin'.
       --efrw, ext-fsb-raw    [SegmentFilePATH]                              > Extracts the raw GCADPCM/DSPADPCM Audio from an *.fsb Soundbank File.
       --edrw, ext-dsp-raw    [GeneratedDspFilePATH]                         > Extracts the raw GCADPCM/DSPADPCM Audio from a Nintendo *.dsp Audio File.
       --rsnd, replace-snd    [SegmentFilePATH]        [DspFilePATH]         > Convert Nintendo *.dsp Audio File to *.fsb Soundbank File.
       --gmtd, get-metadata   [CombinedAudioPATH]                            > Get info such as Header-Size, Number of Audio Files, and if the CombinedAudio.bin Archive has been Modified.
       --upd,  update                                                        > Updates From Current Version to the Latest Version of 'CATool.py'.
       --rstr, restore                                                       > Basically an Emergancy Version of '--upd' that Wipes all Files from CATool and Reinstalls them.
       --h,    help                                                          > Displays this Message.\n\n\n""")
    os.system('pause')

def getSoundId():
    filename = sys.argv[2]
    with open(filename, "rb") as file:
        data = file.read()
    
    fsb5_tag = b"FSB5"
    byte_array = b"\x00\x04\x00\x00\x00"
    null_byte = b"\x00"
    fsb5_positions = []
    start = 0
    while True:
        pos = data.find(fsb5_tag, start)
        if pos == -1:
            break
        fsb5_positions.append(pos)
        start = pos + len(fsb5_tag)
    
    with open('.\\ExtractedSoundIDs.txt','w') as f:
        for fsb5_pos in fsb5_positions:
            search_limit = fsb5_pos + 0xFF
            if search_limit > len(data):
                search_limit = len(data)
        
            array_pos = data.find(byte_array, fsb5_pos, search_limit)
            if array_pos != -1:
                string_start = array_pos + len(byte_array)
                string_end = data.find(null_byte, string_start)
                if string_end != -1:
                    extracted_string = data[string_start:string_end].decode('utf-8', errors='replace')
                    print(f"Extracted string: {extracted_string}")
                    f.write(f"{extracted_string}\n")

def renameSegments():
    directory = sys.argv[2]
    files = [f for f in os.listdir(directory) if f.startswith("segment_") and f.endswith(".fsb")]
    i = 0
    for file_name in files:
        file_path = os.path.join(directory, file_name)
        with open(file_path, 'rb') as file:
            data = file.read(0xFF)
        
        target_sequence = b'\x00\x04\x00\x00\x00'
        index = data.find(target_sequence)
        if index != -1:
            start_index = index + 5
            end_index = start_index
            while end_index < len(data) and data[end_index] != 0x00:
                end_index += 1
            
            new_name = data[start_index:end_index].decode('utf-8')
            new_file_name = new_name + '.fsb'
            new_file_path = os.path.join(directory, new_file_name)
            count = 1
            while os.path.exists(new_file_path):
                new_file_name = f"{new_name}({count}).fsb"
                new_file_path = os.path.join(directory, new_file_name)
                count += 1

            try:
                os.rename(file_path, new_file_path)
                print(f'Renamed "{file_name}" to "{new_file_name}".')

            except FileExistsError:
                pass

def getSize():
    directory = sys.argv[2]
    output_file = ".\\ExtractedAudioSizes.txt"
    with open(output_file, 'w') as out:
        for filename in os.listdir(directory):
            if filename.startswith("segment_") and filename.endswith(".fsb"):
                with open(f"{directory}\\{filename}",'rb') as f:
                    data_length = len(f.read())
                    out.write(f"Filename: {filename} | Bytes: {data_length}.\n")
                    print(f"Wrote: {filename} with {data_length} Bytes, to file: '{output_file}'.")

def getSizeFile():
    audioFile = sys.argv[2]
    baseFile = os.path.basename(audioFile)
    if '.fsb' not in baseFile:
        print(f"Error: File provided '{baseFile}' isn't *.fsb File.")
        sys.exit(1)
    baseFileName = baseFile.replace('.fsb','')
    outFile = f".\\Extracted{baseFileName}Size.txt"
    with open(audioFile,'rb') as f:
        data_length = len(f.read())
        with open(outFile,'w') as of:
            of.write(f"Filename: {baseFileName} | Bytes: {data_length}.\n")
            print(f"Wrote: {baseFileName} with {data_length} Bytes, to file: '{outFile}'.")

def get_latest_release_number():
    url = 'https://github.com/Minecraft-3DS-Community/CombinedAudioTool/releases'
    with urllib.request.urlopen(url) as response:
        html = response.read().decode('utf-8')

    release_pattern = re.compile(r'/Minecraft-3DS-Community/CombinedAudioTool/releases/tag/([^"]+)')
    match = release_pattern.search(html)
    if not match:
        sys.exit(1)

    latest_release_number = match.group(1)
    latest_release_number_float = float(latest_release_number.lstrip('v'))
    return latest_release_number_float

def get_latest_CATool():
    global VERSION
    file_name = 'CATool.py'
    latest_release_version = get_latest_release_number()
    print(f"Script Version: '{VERSION}'.\nLatest Release Version: '{latest_release_version}'.\n")
    if VERSION == latest_release_version:
        print(f"Your '{os.path.basename(__file__)}' Script Version is the Latest Release.")
        sys.exit(1)
    elif VERSION > latest_release_version:
        print(f"Woah!!! Your script must be a part of the Development branch.")
        sys.exit(1)
    else:
        pass

    release_url = f"https://api.github.com/repos/Minecraft-3DS-Community/CombinedAudioTool/releases/latest"
    response = requests.get(release_url)
    release_info = response.json()
    print("\nGetting Latest CATool Version...")

    asset_url = None
    for asset in release_info['assets']:
        if asset['name'] == file_name or asset['name'].endswith('.zip'):
            asset_url = asset['browser_download_url']
            print(f"Most Recent Version: {asset_url}")
            break
    else:
        raise ValueError(f"No asset named '{file_name}' or .zip file found in the latest release.")

    response = requests.get(asset_url)
    if asset['name'].endswith('.zip'):
        print("Downloading and extracting the latest CATool.zip...")
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            z.extractall('.')
        print("Extracted the contents of the latest CATool.zip")
    else:
        print("Downloading CATool...")
        with open(file_name, 'wb') as f:
            f.write(response.content)
        print("Downloaded the latest CATool.")

def self_update():
    print("Updating CATool.py...\n")
    get_latest_CATool()
    time.sleep(1)
    print("Restarting CATool.py...")
    time.sleep(0.5)
    sys.exit()

def errorHandle():
    print("Nintendo GCADPCM Found.\nAttempting New Decoding Algorithm...\n")
    gcadpcmAudio()

def extractAudio():
    try:
        try:
            segment_fsb = sys.argv[2]
            with open(segment_fsb,'rb') as f:
                fsb = fsb5.FSB5(f.read())
    
            ext = fsb.get_sample_extension()
            for sample in fsb.samples:
                print('''\t
                Name: {sample.name}.fsb
                Frequency: {sample.frequency}
                Channels: {sample.channels}
                Samples: {sample.samples}\n'''.format(sample=sample, extension=ext))

            with open('{0}.{1}'.format(sample.name, ext), 'wb') as f:
                rebuilt_sample = fsb.rebuild_sample(sample)
                f.write(rebuilt_sample)
        except ValueError:
            errorHandle()        
    except NotImplementedError:
        errorHandle()

def gcadpcmAudio():
    audio_file = sys.argv[2]
    fileN_0 = os.path.basename(audio_file)
    fileF_0 = os.path.splitext(fileN_0)[0]
    segmentName = find_segment_name()
    if segmentName == None:
        segmentName = 0
    os.system(f'.\\extrcd\\gcadpcm\\cvt.exe -o .\\{fileF_0}_{segmentName}.wav {audio_file}')

def convertAudioGcadpcm():
    originalFile = sys.argv[2] # Required because it's used in find_segment_name()
    file2Convert = sys.argv[3]
    originalFileName = find_segment_name()
    if '.wav' not in file2Convert and '.wave' not in file2Convert:
        print(f"File Provided: '{file2Convert}' is an Invalid Wave File.\nPlease try again with a Valid Wave/RIFF File Format.\n")
        sys.exit(1)
    
    os.system(f'.\\extrcd\\gcadpcm\\encode_soundCli.exe --convert -f GcAdpcm -i "{file2Convert}" -o "{originalFileName}.dsp"')

def playAudio():
    wavFile = sys.argv[2]
    if '.wav' in wavFile or '.wave' in wavFile:
        winsound.PlaySound(wavFile, winsound.SND_FILENAME)
    else:
        print("Invalid Wave File Found.")
        sys.exit(1)

def generateMusic():
    wavFile = sys.argv[2]
    wavFileNE = wavFile.replace('.wav','')
    os.system(f'.\\extrcd\\gen\\other\\fsbCli.exe -build_mode i -format pcm -rebuild -optimize_samplerate -o {wavFileNE}.fsb {wavFile}')

def download_ffmpeg(url, filename):
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(filename, 'wb') as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)

def extract_bin_folder(zip_path, extract_to):
    zip0 = os.path.basename(zip_path)
    zip_folder = zip0.replace(".zip","")
    if os.path.exists(f"{os.path.dirname(__file__)}\\extrcd\\mpg\\bin"):
        print("\n\nFFMPEG Has been installed already.")
        sys.exit(1)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for member in zip_ref.namelist():
            if member.startswith(f'{zip_folder}/bin'):
                zip_ref.extract(member, extract_to)
    
    shutil.copytree(f"{os.path.dirname(__file__)}\\extrcd\\mpg\\{zip_folder}\\bin",f"{os.path.dirname(__file__)}\\extrcd\\mpg\\bin")
    shutil.rmtree(f"{os.path.dirname(__file__)}\\extrcd\\mpg\\{zip_folder}")
    
def install_ffmpeg():
    release_url = f"https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
    msgbx = messagebox.askyesno("Install FFMPEG", "Would you like to install FFMPEG for CATool?")
    if not msgbx:
        sys.exit(1)
    
    response = requests.get(release_url)
    response.raise_for_status()
    release_data = response.json()
    for asset in release_data['assets']:
        if 'win64-gpl-shared' in asset['name']:
            download_url = asset['browser_download_url']
            file_name = asset['name']
            print(f"Downloading {file_name} from {download_url}")
            download_ffmpeg(download_url, file_name)
            print(f"Downloaded {file_name}")
            extract_dir = './extrcd/mpg'
            if not os.path.exists(extract_dir):
                os.makedirs(extract_dir)

            extract_bin_folder(file_name, extract_dir)
            break
    else:
        print("No asset found with the text 'win64-gpl-shared'")

def replaceFSBAudio():
    originalFile = sys.argv[2]
    generateDspFile = sys.argv[3]
    newFile = originalFile.replace('.fsb','_New.fsb')
    dspHeaderSize = 0x60 # Always
    with open(originalFile,'rb') as origF:
        ogLen, ogFileSize = getRawAudioSizeAndData()
        read_data = ogFileSize-ogLen
        ogFileData = origF.read(read_data)
        ogFileLen = ogLen
        with open(generateDspFile,'rb') as dspF:
            dspF.seek(dspHeaderSize)
            dsp_data = dspF.read()
            dspFileLen = len(dsp_data)
            print(f"DSP File Length: {dspFileLen}\nFSB File Length: {ogFileLen}")
    
        if ogFileLen < dspFileLen:
            print(f"\n\nCannot Convert File to Provided *.FSB Soundbank File.\nError Due to Size Limitation.\n")
            sys.exit(1)

        dataDifference = ogFileLen-dspFileLen # MUST BE SMALLER
        with open(newFile,'wb') as f:
            f.write(ogFileData)
            origF.seek(0x14)
            sizeBytes = origF.read(0x04)
            oldValue = int.from_bytes(sizeBytes, byteorder='little')
            newValue = dspFileLen
            newValBytes = newValue.to_bytes(4, byteorder='little')
            f.seek(0x14)
            f.write(newValBytes)
            f.seek(0, 2)
            f.write(dsp_data)

def extractRawAudioFromDSP():
    dspFile = sys.argv[2]
    rawDspFile = dspFile.replace('.dsp','.rawdsp')
    with open(dspFile,'rb') as ogF:
        ogF.seek(0x60)
        data = ogF.read()
    
    with open(rawDspFile,'wb') as f:
        f.write(data)

def extractRawAudioFromFSB():
    fsbFile = sys.argv[2]
    rawFsbFile = fsbFile.replace('.fsb','.rawfsb')
    with open(fsbFile,'rb') as f:
        f.seek(0x14)
        data = f.read(4)
        value = int.from_bytes(data, byteorder='little')
        f.seek(0, 2)
        file_size = f.tell()
        seek_position = file_size - value
        f.seek(seek_position)
        gcadpcm_audio = f.read()
        f.close()
    with open(rawFsbFile,'wb') as of:
        of.write(gcadpcm_audio)
        of.close()

def getRawAudioSizeAndData():
    file0 = sys.argv[2]
    with open(file0,'rb') as f:
        f.seek(0x14)
        data = f.read(4)
        value = int.from_bytes(data, byteorder='little')
        f.seek(0, 2)
        file_size = f.tell()
        seek_position = file_size - value
        f.seek(seek_position)
        gcadpcm_audio = f.read()
        gcadpcm_len = len(gcadpcm_audio)
        f.close()
        return gcadpcm_len, file_size

def count_specific_bytes():
    file_path = sys.argv[2]
    search_string = b'FSB5'
    sixCount = 0
    twoCount = 0
    celtCount = 0
    fmodCount = 0
    oneCount = 0
    interleavedFormat = 0

    with open(file_path, 'rb') as file:
        file_content = file.read()
        position = 0
        
        while position != -1:
            position = file_content.find(search_string, position)
            
            if position == -1:
                break

            skip_position = position + len(search_string) + 0x14
            if skip_position < len(file_content):
                byte_value = file_content[skip_position]

                if byte_value == 0x06:
                    sixCount += 1
                elif byte_value == 0x02:
                    twoCount += 1
                elif byte_value == 0x07:
                    fmodCount += 1
                elif byte_value == 0x01:
                    oneCount += 1
                else:
                    celtCount += 1

            interleaved_position = position + len(search_string) + 0x20
            if interleaved_position < len(file_content) and byte_value == 0x06:
                interleaved_byte_value = file_content[interleaved_position]

                if interleaved_byte_value == 0x02:
                    interleavedFormat += 1
            
            position += len(search_string)
    
    return sixCount, twoCount, celtCount, fmodCount, oneCount, interleavedFormat

def getMetaData():
    combinedAudiof = sys.argv[2]
    backupFile = f".\\extrcd\\def_aud.bin"
    searchStr = b'FSB5'
    count = 0
    with open(combinedAudiof, 'rb') as file:
        data0 = file.read()
        count = data0.count(searchStr)
        file.seek(0x00)
        position = data0.find(searchStr)
        if position == -1:
            raise ValueError("The search string was not found in the file.")
        lngth = len(data0[:position])

    with open(backupFile,'rb') as f1:
        data1 = f1.read()

    if data0 != data1:
        answer = 'Yes'
    else:
        answer = "No"

    sixCount, twoCount, celtCount, fmodCount, oneCount, interleavedFormat = count_specific_bytes()
    print(f"""
Has File Been Modified?           - {answer}.
Header Length?                    - {lngth}.
How Many Audio Files?             - {count}.

How Many GCADPCM File Formats?    - {sixCount}.
How Many GCADPCM Interleaved?     - {interleavedFormat}.
How Many GCADPCM Flat?            - {sixCount-interleavedFormat}

How Many PCM8 File Formats?       - {oneCount}.
How Many PCM16 File Formats?      - {twoCount}.
How Many CELT File Formats?       - {celtCount}.
How Many IMAFMOD File Formats?    - {fmodCount}.
        \n""")


if __name__ == '__main__':
    try:
        latest_release = get_latest_release_number()
        if os.path.exists('force-s.bin') == False:
            if type(latest_release) == float:
                if latest_release > VERSION:
                    print(f"\nA new version of CombinedAudioTool (CATool) is Avaliable.\nUse '--upd' to Get the Latest Release!")
            else:
                print("\nNo Internet Avaliable, please connect to the Internet to Check your Version or Update it.")

        callable = sys.argv[1]
        if callable == 'extract-ca' or callable == '--eca':
            extrCombAudio()

        if callable == 'find-sn' or callable == '--fn':
            print(find_segment_name())

        if callable == 'rename-s' or callable == '--rs':
            rename_segment()

        if callable == 'get-header' or callable == '--gh':
            collect_header()

        if callable == 'rebuild-ca' or callable == '--rca':
            rebCombAudio()

        if callable == 'add-padding' or callable == '--ap':
            addPadding()

        if callable == "name-extract" or callable == '--ne':
            extractByName()

        if callable == 'help' or callable == '--h':
            info_help()

        if callable == 'get-soundid' or callable == '--gsid':
            getSoundId()

        if callable == 'rename-all' or callable == '--ra':
            renameSegments()

        if callable == 'get-size' or callable == '--gs':
            getSize()

        if callable == 'get-size-seg' or callable == '--gssg':
            getSizeFile()

        if callable == 'extract-seg' or callable == '--exa':
            extractAudio()

        if callable == 'update' or callable == '--upd':
            self_update()

        if callable == 'restore' or callable == '--rstr':
            if os.path.exists('.\\extrcd') != True:
                restoreToolInt()
            else:
                pass

        if callable == 'convert-wave' or callable == '--cwav':
            convertAudioGcadpcm()

        if callable == 'play-audio' or callable == '--pa':
            playAudio()
        
        if callable == 'generate-music' or callable == '--gmsc':
            generateMusic()

        if callable == 'to-wave' or callable == '--atw':
            formatsToWave()

        if callable == '--impg' or callable == 'inst-ffmpeg':
            install_ffmpeg()

        if callable == 'ext-fsb-raw' or callable == '--efrw':
            extractRawAudioFromFSB()

        if callable == 'ext-dsp-raw' or callable == '--edrw':
            extractRawAudioFromDSP()

        if callable == 'replace-snd' or callable == '--rsnd':
            replaceFSBAudio()

        if callable == 'get-metadata' or callable == '--gmtd':
            getMetaData()

    except IndexError:
        info_help()