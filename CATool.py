import io
import json
import os
import struct
import shutil
import subprocess
import sys
import tempfile
import traceback
import wave
from dataclasses import dataclass

import numpy as np
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_TITLE = "CATool GUI"
APP_VERSION = "2.5"
DSP_HEADER_SIZE = 0x60
COMBINED_AUDIO_HEADER_SIZE = 0x1A2C
COMBINED_AUDIO_ALIGNMENT = 0x20


def resource_path(*parts: str) -> Path:
    base = Path(__file__).resolve().parent
    return base.joinpath(*parts)


@dataclass
class DspHeader:
    sample_count: int
    nibble_count: int
    sample_rate: int
    loop_flag: int
    fmt: int
    loop_start: int
    loop_end: int
    current_address: int
    channels: int
    block_size: int
    coeff_blob: bytes
    raw_header: bytes
    data_offset: int


@dataclass
class CombinedAudioEntry:
    table_index: int
    sound_id: int
    offset: int  # stored table offset, relative to the start of the FSB data region
    size: int
    end_offset: int  # stored relative end offset
    absolute_offset: int = 0
    absolute_end_offset: int = 0
    physical_index: int = -1
    fsb_name: str = ""


class ToolError(Exception):
    pass


class CAToolBackend:
    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent
        self.cvt_exe = resource_path("extrcd", "gcadpcm", "cvt.exe")
        self.enc_exe = resource_path("extrcd", "gcadpcm", "encode_soundCli.exe")

    def run_process(self, args, cwd=None):
        try:
            result = subprocess.run(
                args,
                cwd=str(cwd or self.base_dir),
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip() or result.stderr.strip() or "Completed."
        except subprocess.CalledProcessError as exc:
            raise ToolError((exc.stderr or exc.stdout or str(exc)).strip()) from exc
        except FileNotFoundError as exc:
            raise ToolError(f"Missing executable: {args[0]}") from exc

    def ensure_exists(self, path: Path, kind="File"):
        if not Path(path).exists():
            raise ToolError(f"{kind} not found: {path}")

    def _parse_single_dsp_header(self, header: bytes):
        if len(header) < DSP_HEADER_SIZE:
            raise ToolError("DSP file is smaller than 0x60-byte header.")

        sample_count = struct.unpack_from(">I", header, 0x00)[0]
        nibble_count = struct.unpack_from(">I", header, 0x04)[0]
        sample_rate = struct.unpack_from(">I", header, 0x08)[0]
        loop_flag = struct.unpack_from(">H", header, 0x0C)[0]
        fmt = struct.unpack_from(">H", header, 0x0E)[0]
        loop_start = struct.unpack_from(">I", header, 0x10)[0]
        loop_end = struct.unpack_from(">I", header, 0x14)[0]
        current_address = struct.unpack_from(">I", header, 0x18)[0]
        channels_hint = struct.unpack_from(">h", header, 0x4A)[0]
        block_size = struct.unpack_from(">H", header, 0x4C)[0]
        coeff_blob = header[0x1C:0x4A]

        if loop_flag not in (0, 1):
            raise ToolError(f"Invalid DSP loop flag: {loop_flag}")
        if fmt != 0:
            raise ToolError(f"Unsupported DSP format value: {fmt}. Expected 0 for ADPCM.")
        if sample_count <= 0 or nibble_count <= 0:
            raise ToolError("DSP header has invalid sample or nibble counts.")
        if sample_rate < 5000 or sample_rate > 48000:
            raise ToolError("DSP header has invalid sample rate.")

        return {
            "sample_count": sample_count,
            "nibble_count": nibble_count,
            "sample_rate": sample_rate,
            "loop_flag": loop_flag,
            "fmt": fmt,
            "loop_start": loop_start,
            "loop_end": loop_end,
            "current_address": current_address,
            "channels_hint": channels_hint,
            "block_size": block_size,
            "coeff_blob": coeff_blob,
            "raw_header": header,
        }

    def read_dsp_header(self, dsp_path: Path) -> DspHeader:
        self.ensure_exists(dsp_path)
        data = Path(dsp_path).read_bytes()
        if len(data) < DSP_HEADER_SIZE:
            raise ToolError("DSP file is smaller than 0x60-byte header.")

        h1 = self._parse_single_dsp_header(data[:DSP_HEADER_SIZE])
        channels = 1
        coeff_blob = h1["coeff_blob"]
        raw_header = h1["raw_header"]
        data_offset = DSP_HEADER_SIZE

        # Standard stereo DSPs commonly store a second full 0x60-byte header at 0x60,
        # followed by the interleaved ADPCM payload at 0xC0.
        if len(data) >= DSP_HEADER_SIZE * 2:
            try:
                h2 = self._parse_single_dsp_header(data[DSP_HEADER_SIZE:DSP_HEADER_SIZE * 2])
            except ToolError:
                h2 = None
            if h2 and all(h1[k] == h2[k] for k in ("sample_count", "nibble_count", "sample_rate", "loop_flag", "fmt")):
                channels = 2
                coeff_blob = h1["coeff_blob"] + h2["coeff_blob"]
                raw_header = data[:DSP_HEADER_SIZE * 2]
                data_offset = DSP_HEADER_SIZE * 2

        hint = h1["channels_hint"]
        if channels == 1 and hint in (1, 2):
            channels = hint
            if channels == 2:
                raise ToolError("DSP header says 2 channels, but no valid second DSP header was found. Re-encode the WAV as mono or use a standard stereo DSP file.")

        return DspHeader(
            sample_count=h1["sample_count"],
            nibble_count=h1["nibble_count"],
            sample_rate=h1["sample_rate"],
            loop_flag=h1["loop_flag"],
            fmt=h1["fmt"],
            loop_start=h1["loop_start"],
            loop_end=h1["loop_end"],
            current_address=h1["current_address"],
            channels=channels,
            block_size=h1["block_size"],
            coeff_blob=coeff_blob,
            raw_header=raw_header,
            data_offset=data_offset,
        )

    def _align_up(self, value: int, alignment: int = COMBINED_AUDIO_ALIGNMENT) -> int:
        if alignment <= 0:
            return value
        return (value + alignment - 1) & ~(alignment - 1)

    def parse_combined_audio_table(self, combined_audio_path: Path):
        self.ensure_exists(combined_audio_path)
        data = Path(combined_audio_path).read_bytes()
        if len(data) < 4:
            raise ToolError("CombinedAudio.bin is too small to contain an entry count.")
        entry_count = struct.unpack_from('<I', data, 0)[0]
        header_length = 4 + (entry_count * 12)
        if entry_count <= 0:
            raise ToolError(f"CombinedAudio entry count is invalid: {entry_count}")
        if header_length > len(data):
            raise ToolError("CombinedAudio header extends past the end of the file.")

        entries = []
        for i in range(entry_count):
            off = 4 + (i * 12)
            sound_id, fsb_offset, fsb_size = struct.unpack_from('<III', data, off)
            end_offset = fsb_offset + fsb_size
            absolute_offset = header_length + fsb_offset
            absolute_end_offset = absolute_offset + fsb_size
            if absolute_end_offset > len(data):
                raise ToolError(
                    f"CombinedAudio entry {i} points outside the file "
                    f"(stored_offset={fsb_offset}, absolute_offset=0x{absolute_offset:X}, size={fsb_size})."
                )
            entries.append(CombinedAudioEntry(
                table_index=i,
                sound_id=sound_id,
                offset=fsb_offset,
                size=fsb_size,
                end_offset=end_offset,
                absolute_offset=absolute_offset,
                absolute_end_offset=absolute_end_offset,
            ))

        physical = sorted(entries, key=lambda e: (e.absolute_offset, e.table_index))
        for physical_index, entry in enumerate(physical):
            entry.physical_index = physical_index
            blob = data[entry.absolute_offset:entry.absolute_end_offset]
            if blob[:4] == b'FSB5':
                try:
                    entry.fsb_name = self.get_segment_name_bytes(blob) or ''
                except Exception:
                    entry.fsb_name = ''
            else:
                entry.fsb_name = ''

        return {
            'entry_count': entry_count,
            'header_length': header_length,
            'file_size': len(data),
            'entries': entries,
            'entries_by_physical': physical,
            'header_bytes': data[:header_length],
            'data': data,
        }

    def get_segment_name_bytes(self, fsb_bytes: bytes):
        if len(fsb_bytes) < 0x18 or fsb_bytes[:4] != b'FSB5':
            return None
        try:
            offset_value = struct.unpack_from('<I', fsb_bytes, 0x14)[0]
            pos = len(fsb_bytes) - offset_value
            if pos < 0 or pos >= len(fsb_bytes):
                return None
            decoded = ''
            started = False
            while pos > 0:
                pos -= 1
                byte_value = fsb_bytes[pos]
                if byte_value == 0x00:
                    if started:
                        break
                    continue
                if byte_value == 0x04:
                    break
                if 32 <= byte_value <= 126:
                    decoded += chr(byte_value)
                    started = True
                elif started:
                    break
            return decoded[::-1] if decoded else None
        except Exception:
            return None

    def find_segments(self, file_path: Path):
        parsed = self.parse_combined_audio_table(file_path)
        data = parsed['data']
        segments = []
        for entry in parsed['entries_by_physical']:
            blob = data[entry.absolute_offset:entry.absolute_end_offset]
            segments.append((entry.absolute_offset, entry.absolute_end_offset, blob, entry))
        return segments

    def extract_combined_audio(self, combined_audio_path: Path, out_dir: Path):
        self.ensure_exists(combined_audio_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        parsed = self.parse_combined_audio_table(combined_audio_path)
        manifest = {
            'source_file': str(combined_audio_path),
            'entry_count': parsed['entry_count'],
            'header_length': parsed['header_length'],
            'alignment': COMBINED_AUDIO_ALIGNMENT,
            'segments': [],
        }
        for entry in parsed['entries_by_physical']:
            blob = parsed['data'][entry.absolute_offset:entry.absolute_end_offset]
            seg_name = f"segment_{entry.physical_index}.fsb"
            (out_dir / seg_name).write_bytes(blob)
            manifest['segments'].append({
                'segment_index': entry.physical_index,
                'table_index': entry.table_index,
                'sound_id': entry.sound_id,
                'offset': entry.offset,
                'size': entry.size,
                'fsb_name': entry.fsb_name,
                'filename': seg_name,
            })
        (out_dir / 'combinedaudio_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        (out_dir / 'header_data.bin').write_bytes(parsed['header_bytes'])
        return len(parsed['entries'])

    def collect_header(self, combined_audio_path: Path, out_dir: Path):
        self.ensure_exists(combined_audio_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        parsed = self.parse_combined_audio_table(combined_audio_path)
        out_path = out_dir / 'header_data.bin'
        out_path.write_bytes(parsed['header_bytes'])
        return out_path

    def _load_combined_manifest(self, segment_dir: Path):
        manifest_path = segment_dir / 'combinedaudio_manifest.json'
        if not manifest_path.exists():
            return None
        return json.loads(manifest_path.read_text(encoding='utf-8'))

    def rebuild_combined_audio(self, segment_dir: Path, output_path: Path):
        segment_dir = Path(segment_dir)
        manifest = self._load_combined_manifest(segment_dir)
        if manifest:
            entry_count = int(manifest['entry_count'])
            segments_info = sorted(manifest['segments'], key=lambda item: int(item['segment_index']))
            if len(segments_info) != entry_count:
                raise ToolError(f"Manifest has {len(segments_info)} segment records but header expects {entry_count} entries.")
            segment_files = []
            for item in segments_info:
                seg_path = segment_dir / item['filename']
                self.ensure_exists(seg_path)
                segment_files.append((item, seg_path))
        else:
            header_path = segment_dir / 'header_data.bin'
            self.ensure_exists(header_path)
            header_data = header_path.read_bytes()
            if len(header_data) < 4:
                raise ToolError('header_data.bin is too small.')
            entry_count = struct.unpack_from('<I', header_data, 0)[0]
            segment_paths = sorted(segment_dir.glob('segment_*.fsb'), key=lambda p: int(p.stem.split('_')[-1]))
            if len(segment_paths) != entry_count:
                raise ToolError('combinedaudio_manifest.json is missing and the number of segment_*.fsb files does not match header_data.bin entry count.')
            segment_files = [({'segment_index': i, 'table_index': i, 'sound_id': 0, 'filename': p.name}, p) for i, p in enumerate(segment_paths)]

        entries = [None] * entry_count
        data_chunks = []
        header_length = 4 + (entry_count * 12)
        current_offset = 0
        for item, seg_path in segment_files:
            blob = seg_path.read_bytes()
            if blob[:4] != b'FSB5':
                raise ToolError(f"{seg_path.name} is not an FSB5 file.")
            current_offset = self._align_up(current_offset)
            table_index = int(item['table_index'])
            sound_id = int(item.get('sound_id', 0))
            entries[table_index] = (sound_id, current_offset, len(blob))
            data_chunks.append((current_offset, blob))
            current_offset += len(blob)

        if any(entry is None for entry in entries):
            missing = [str(i) for i, entry in enumerate(entries) if entry is None][:10]
            raise ToolError(f"CombinedAudio rebuild is missing table entries: {', '.join(missing)}")

        header = bytearray(4 + (entry_count * 12))
        struct.pack_into('<I', header, 0, entry_count)
        for idx, (sound_id, fsb_offset, fsb_size) in enumerate(entries):
            struct.pack_into('<III', header, 4 + (idx * 12), sound_id, fsb_offset, fsb_size)

        out = bytearray(header)
        for fsb_offset, blob in data_chunks:
            absolute_offset = header_length + fsb_offset
            if len(out) < absolute_offset:
                out.extend(b'\x00' * (absolute_offset - len(out)))
            elif len(out) > absolute_offset:
                raise ToolError('Internal rebuild overlap detected while writing CombinedAudio FSB data.')
            out.extend(blob)

        Path(output_path).write_bytes(bytes(out))
        return output_path

    def get_segment_name(self, fsb_path: Path):
        self.ensure_exists(fsb_path)
        return self.get_segment_name_bytes(Path(fsb_path).read_bytes())

    def rename_segment(self, fsb_path: Path):
        name = self.get_segment_name(fsb_path)
        if not name:
            raise ToolError("No embedded segment name was found.")
        new_path = fsb_path.with_name(f"{name}.fsb")
        fsb_path.rename(new_path)
        return new_path

    def rename_all_segments(self, folder: Path):
        renamed = []
        for fsb_path in sorted(folder.glob("segment_*.fsb")):
            try:
                target = self.rename_segment(fsb_path)
                renamed.append((fsb_path.name, target.name))
            except Exception:
                continue
        return renamed

    def extract_raw_from_fsb(self, fsb_path: Path, out_path: Path = None):
        data = self._extract_fsb_payload(fsb_path)
        if out_path is None:
            out_path = fsb_path.with_suffix(".rawfsb")
        Path(out_path).write_bytes(data)
        return Path(out_path)

    def extract_raw_from_dsp(self, dsp_path: Path, out_path: Path = None):
        self.ensure_exists(dsp_path)
        dsp = self.read_dsp_header(dsp_path)
        with open(dsp_path, "rb") as f:
            f.seek(dsp.data_offset)
            data = f.read()
        if out_path is None:
            out_path = dsp_path.with_suffix(".rawdsp")
        Path(out_path).write_bytes(data)
        return Path(out_path)

    def _extract_fsb_payload(self, fsb_path: Path) -> bytes:
        self.ensure_exists(fsb_path)
        with open(fsb_path, "rb") as f:
            f.seek(0x14)
            data_size = struct.unpack("<I", f.read(4))[0]
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            f.seek(file_size - data_size)
            return f.read(data_size)

    def _parse_fsb_header(self, blob: bytes):
        if blob[:4] != b"FSB5":
            raise ToolError("Provided file is not an FSB5 file.")
        version, num_samples, sample_header_size, name_table_size, data_size, mode = struct.unpack_from("<IIIIII", blob, 4)
        if num_samples != 1:
            raise ToolError("This GUI currently supports DSP replacement for single-sample FSB files only.")
        file_header_size = 60 if version == 1 else 64
        sample_header_off = file_header_size
        sample_header = bytearray(blob[sample_header_off:sample_header_off + sample_header_size])
        name_table_off = sample_header_off + sample_header_size
        data_off = name_table_off + name_table_size

        if len(sample_header) < 8:
            raise ToolError("FSB sample header is too small.")
        word1 = struct.unpack_from("<I", sample_header, 0)[0]
        word2 = struct.unpack_from("<I", sample_header, 4)[0]
        channels_code = (word1 >> 5) & 0x03
        channels = {0: 1, 1: 2, 2: 6, 3: 8}.get(channels_code, 1)
        sample_rate_code = (word1 >> 1) & 0x0F

        return {
            "version": version,
            "num_samples": num_samples,
            "sample_header_size": sample_header_size,
            "name_table_size": name_table_size,
            "data_size": data_size,
            "mode": mode,
            "file_header_size": file_header_size,
            "sample_header_off": sample_header_off,
            "name_table_off": name_table_off,
            "data_off": data_off,
            "sample_header": sample_header,
            "word1": word1,
            "word2": word2,
            "channels": channels,
            "sample_rate_code": sample_rate_code,
        }

    def _iter_sample_chunks(self, sample_header: bytearray):
        if len(sample_header) < 8:
            raise ToolError("Sample header is too small.")
        pos = 8
        while pos + 4 <= len(sample_header):
            raw = struct.unpack_from("<I", sample_header, pos)[0]
            next_flag = raw & 0x1
            size = (raw >> 1) & 0xFFFFFF
            chunk_type = (raw >> 25) & 0x7F
            data_start = pos + 4
            data_end = data_start + size
            if data_end > len(sample_header):
                raise ToolError("FSB sample header chunk exceeds header bounds.")
            yield {
                "header_offset": pos,
                "type": chunk_type,
                "size": size,
                "data_offset": data_start,
                "data_end": data_end,
                "next_flag": next_flag,
            }
            pos = data_end
            if not next_flag:
                break

    def wrap_dsp_into_fsb(self, template_fsb: Path, dsp_path: Path, out_path: Path):
        self.ensure_exists(template_fsb)
        self.ensure_exists(dsp_path)
        dsp = self.read_dsp_header(dsp_path)
        if dsp.fmt != 0:
            raise ToolError(f"Unsupported DSP format value: {dsp.fmt}. Expected 0.")

        blob = bytearray(template_fsb.read_bytes())
        meta = self._parse_fsb_header(blob)
        if meta["mode"] != 6:
            raise ToolError("Template FSB is not GCADPCM (mode 6).")

        sample_header = meta["sample_header"]
        payload_bytes = Path(dsp_path).read_bytes()
        payload = payload_bytes[dsp.data_offset:]
        if not payload:
            raise ToolError(f"DSP contains no ADPCM payload after the {dsp.data_offset:#x}-byte header area.")

        found_channels = False
        found_freq = False
        found_loop = False
        found_dspcoeff = False

        # FSB5 stores the packed sample header as one 64-bit little-endian value.
        # Layout from fsb5_spec.c:
        #   bits 63..34 = num_samples (30 bits)
        #   bits 33..7  = data offset within data section, in 0x20-byte units (27 bits incl. shift)
        #   bits 7..6   = default channel code
        #   bits 5..1   = default sample-rate code
        #   bit 0       = has extra chunks
        #
        # The previous build incorrectly overwrote the low 30 bits of word2, but num_samples
        # actually lives in the high 30 bits of the 64-bit value. That leaves the template's
        # original duration in place, which is why playback stopped at the template length.
        sample_mode = struct.unpack_from("<Q", sample_header, 0)[0]
        sample_mode = (sample_mode & ((1 << 34) - 1)) | ((dsp.sample_count & 0x3FFFFFFF) << 34)
        struct.pack_into("<Q", sample_header, 0, sample_mode)

        for chunk in self._iter_sample_chunks(sample_header):
            ctype = chunk["type"]
            cstart = chunk["data_offset"]
            cend = chunk["data_end"]
            csize = chunk["size"]
            if ctype == 1 and csize >= 1:
                sample_header[cstart] = dsp.channels & 0xFF
                found_channels = True
            elif ctype == 2 and csize == 4:
                struct.pack_into("<I", sample_header, cstart, dsp.sample_rate)
                found_freq = True
            elif ctype == 3 and csize == 8:
                # DSP loop values are nibble offsets, but FSB loop info stores samples.
                loop_start_samples = max(0, (dsp.loop_start - 2) // 8 * 14)
                loop_end_samples = max(0, ((dsp.loop_end - 2) // 8 * 14) + 1)
                struct.pack_into("<II", sample_header, cstart, loop_start_samples, loop_end_samples)
                found_loop = True
            elif ctype == 7:
                if csize != len(dsp.coeff_blob):
                    hint = ""
                    if csize == 46 and len(dsp.coeff_blob) == 92:
                        hint = " The template is mono (1ch) and the DSP is stereo (2ch). Use a stereo template FSB or re-encode the WAV as mono DSP."
                    elif csize == 92 and len(dsp.coeff_blob) == 46:
                        hint = " The template is stereo (2ch) and the DSP is mono (1ch). Use a mono template FSB or a stereo DSP."
                    raise ToolError(
                        f"Template DSP coefficient chunk is {csize} bytes, but DSP header block is {len(dsp.coeff_blob)} bytes. "
                        f"This usually means the template is {meta['channels']}ch and the DSP is {dsp.channels}ch, or the template uses a different DSP extra-data layout." + hint
                    )
                sample_header[cstart:cend] = dsp.coeff_blob
                found_dspcoeff = True

        # If there is no explicit channel chunk, the packed header bits must already match.
        if not found_channels and meta["channels"] != dsp.channels:
            raise ToolError(
                f"Template FSB is {meta['channels']} channel(s), but DSP is {dsp.channels} channel(s). "
                "Use a template with the same channel count as the DSP input."
            )

        if not found_dspcoeff:
            raise ToolError("Template FSB does not contain a DSPCOEFF chunk, so it cannot be safely used as a GCADPCM wrapper template.")
        if not found_freq:
            raise ToolError("Template FSB does not contain a FREQUENCY chunk.")
        if dsp.loop_flag and not found_loop:
            raise ToolError("DSP is looped, but template FSB does not contain a LOOP chunk.")

        # Write back modified sample header.
        blob[meta["sample_header_off"]:meta["sample_header_off"] + meta["sample_header_size"]] = sample_header

        # Update file-level data size.
        struct.pack_into("<I", blob, 0x14, len(payload))

        # Replace sample data area.
        rebuilt = bytes(blob[:meta["data_off"]]) + payload
        Path(out_path).write_bytes(rebuilt)
        return Path(out_path)

    def _dsp_clamp16(self, value: int) -> int:
        return max(-32768, min(32767, int(value)))

    def _dsp_samples_to_nibbles(self, sample_count: int) -> int:
        frames = (sample_count + 13) // 14
        return frames * 16

    def _dsp_sample_to_nibble_address(self, sample_index: int) -> int:
        frame = sample_index // 14
        index_in_frame = sample_index % 14
        return frame * 16 + 2 + index_in_frame

    def _load_wav_pcm16(self, wav_path: Path):
        self.ensure_exists(wav_path)
        with wave.open(str(wav_path), 'rb') as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            sample_rate = wf.getframerate()
            frame_count = wf.getnframes()
            comptype = wf.getcomptype()
            if comptype != 'NONE':
                raise ToolError('Only uncompressed PCM WAV files are supported for Python DSP encoding.')
            if sampwidth != 2:
                raise ToolError('Only 16-bit PCM WAV files are supported for Python DSP encoding.')
            if channels not in (1, 2):
                raise ToolError('Only mono or stereo WAV files are supported for Python DSP encoding.')
            raw = wf.readframes(frame_count)
        samples = np.frombuffer(raw, dtype='<i2').astype(np.int16).reshape(-1, channels)
        return sample_rate, channels, samples

    def _estimate_dsp_coefs(self, pcm: np.ndarray):
        x = pcm.astype(np.float64)
        if len(x) < 64:
            return [(0, 0), (2048, 0), (1024, 0), (512, 0), (1536, -512), (1024, -512), (1536, -1024), (0, 0)]

        y = x[2:]
        h1 = x[1:-1]
        h2 = x[:-2]
        H = np.stack([h1, h2], axis=1)
        try:
            a, _, _, _ = np.linalg.lstsq(H, y, rcond=None)
            a1, a2 = float(a[0]), float(a[1])
        except np.linalg.LinAlgError:
            a1, a2 = 0.0, 0.0

        variants = [
            (0.0, 0.0),
            (a1, a2),
            (a1 * 0.75, a2 * 0.75),
            (a1 * 0.5, a2 * 0.5),
            (min(a1 * 1.1, 1.8), max(a2 * 1.1, -1.8)),
            (min(a1 * 0.9, 1.8), max(a2 * 0.9, -1.8)),
            (1.0, 0.0),
            (0.9375, -0.46875),
        ]
        out = []
        seen = set()
        for fa1, fa2 in variants:
            c1 = max(-32768, min(32767, int(round(fa1 * 2048.0))))
            c2 = max(-32768, min(32767, int(round(fa2 * 2048.0))))
            pair = (c1, c2)
            if pair not in seen:
                seen.add(pair)
                out.append(pair)
        while len(out) < 8:
            out.append((0, 0))
        return out[:8]

    def _decode_dsp_sample(self, nibble: int, scale_shift: int, coef1: int, coef2: int, hist1: int, hist2: int) -> int:
        scale = 1 << scale_shift
        val = (((nibble * scale) << 11) + 1024 + (coef1 * hist1) + (coef2 * hist2)) >> 11
        return self._dsp_clamp16(val)

    def _choose_best_dsp_frame(self, pcm_block, coefs, hist1: int, hist2: int):
        best_error = None
        best = None
        frame_len = len(pcm_block)
        for pred_idx, (coef1, coef2) in enumerate(coefs):
            th1, th2 = hist1, hist2
            max_residual = 0
            for i in range(frame_len):
                predicted = ((coef1 * th1) + (coef2 * th2) + 1024) >> 11
                residual = int(pcm_block[i]) - predicted
                if abs(residual) > max_residual:
                    max_residual = abs(residual)
                th2, th1 = th1, int(pcm_block[i])

            scale_shift = 0
            while scale_shift < 12 and max_residual > (7 << scale_shift):
                scale_shift += 1
            trial_shifts = sorted(set(max(0, min(12, scale_shift + d)) for d in (-1, 0, 1, 2)))

            for ss in trial_shifts:
                cur_hist1, cur_hist2 = hist1, hist2
                nibbles = []
                total_error = 0
                for i in range(frame_len):
                    predicted = ((coef1 * cur_hist1) + (coef2 * cur_hist2) + 1024) >> 11
                    residual = int(pcm_block[i]) - predicted
                    scale = 1 << ss
                    q = int(round(residual / scale))
                    q = max(-8, min(7, q))
                    decoded = self._decode_dsp_sample(q, ss, coef1, coef2, cur_hist1, cur_hist2)
                    err = int(pcm_block[i]) - decoded
                    total_error += err * err
                    cur_hist2, cur_hist1 = cur_hist1, decoded
                    nibbles.append(q & 0xF)
                if best_error is None or total_error < best_error:
                    best_error = total_error
                    best = (pred_idx, ss, nibbles, cur_hist1, cur_hist2)
        return best

    def _pack_dsp_frame(self, pred_idx: int, scale_shift: int, nibbles):
        header = ((pred_idx & 0xF) << 4) | (scale_shift & 0xF)
        out = bytearray([header])
        padded = list(nibbles)
        while len(padded) < 14:
            padded.append(0)
        for i in range(0, 14, 2):
            out.append(((padded[i] & 0xF) << 4) | (padded[i + 1] & 0xF))
        return bytes(out)

    def _encode_pcm_channel_to_dsp(self, pcm: np.ndarray, sample_rate: int, loop_start=None, loop_end=None):
        pcm = pcm.astype(np.int16)
        sample_count = len(pcm)
        if loop_start is not None and loop_end is not None:
            if not (0 <= loop_start < loop_end <= sample_count):
                raise ToolError('Invalid DSP loop points.')
            loop_flag = 1
            loop_start_nibble = self._dsp_sample_to_nibble_address(loop_start)
            loop_end_nibble = self._dsp_sample_to_nibble_address(loop_end - 1)
        else:
            loop_flag = 0
            loop_start_nibble = 0
            loop_end_nibble = self._dsp_sample_to_nibble_address(sample_count - 1) if sample_count > 0 else 0

        coefs = self._estimate_dsp_coefs(pcm)
        frames = []
        hist1 = 0
        hist2 = 0
        initial_ps = 0
        initial_hist1 = 0
        initial_hist2 = 0
        loop_ps = 0
        loop_hist1 = 0
        loop_hist2 = 0
        loop_frame_index = (loop_start // 14) if loop_flag else -1

        for frame_index, start in enumerate(range(0, sample_count, 14)):
            block = pcm[start:start + 14]
            pred_idx, scale_shift, nibbles, new_hist1, new_hist2 = self._choose_best_dsp_frame(block, coefs, hist1, hist2)
            if frame_index == 0:
                initial_ps = ((pred_idx & 0xF) << 4) | (scale_shift & 0xF)
                initial_hist1 = hist1
                initial_hist2 = hist2
            if loop_flag and frame_index == loop_frame_index:
                loop_ps = ((pred_idx & 0xF) << 4) | (scale_shift & 0xF)
                loop_hist1 = hist1
                loop_hist2 = hist2
            frames.append(self._pack_dsp_frame(pred_idx, scale_shift, nibbles))
            hist1, hist2 = new_hist1, new_hist2

        coeff_blob = b''.join(struct.pack('>hh', c1, c2) for c1, c2 in coefs)
        return {
            'sample_count': sample_count,
            'nibble_count': self._dsp_samples_to_nibbles(sample_count),
            'sample_rate': sample_rate,
            'loop_flag': loop_flag,
            'loop_start_nibble': loop_start_nibble,
            'loop_end_nibble': loop_end_nibble,
            'current_address': 0,
            'coeff_blob': coeff_blob,
            'initial_ps': initial_ps,
            'initial_hist1': initial_hist1,
            'initial_hist2': initial_hist2,
            'loop_ps': loop_ps if loop_flag else 0,
            'loop_hist1': loop_hist1 if loop_flag else 0,
            'loop_hist2': loop_hist2 if loop_flag else 0,
            'adpcm_bytes': b''.join(frames),
        }

    def _build_single_dsp_header(self, encoded: dict, channels_hint: int, block_size: int) -> bytes:
        header = bytearray(DSP_HEADER_SIZE)
        struct.pack_into('>I', header, 0x00, encoded['sample_count'])
        struct.pack_into('>I', header, 0x04, encoded['nibble_count'])
        struct.pack_into('>I', header, 0x08, encoded['sample_rate'])
        struct.pack_into('>H', header, 0x0C, encoded['loop_flag'])
        struct.pack_into('>H', header, 0x0E, 0)
        struct.pack_into('>I', header, 0x10, encoded['loop_start_nibble'])
        struct.pack_into('>I', header, 0x14, encoded['loop_end_nibble'])
        struct.pack_into('>I', header, 0x18, encoded['current_address'])
        header[0x1C:0x1C + len(encoded['coeff_blob'])] = encoded['coeff_blob']
        struct.pack_into('>H', header, 0x3C, 0)
        struct.pack_into('>H', header, 0x3E, encoded['initial_ps'])
        struct.pack_into('>h', header, 0x40, encoded['initial_hist1'])
        struct.pack_into('>h', header, 0x42, encoded['initial_hist2'])
        struct.pack_into('>H', header, 0x44, encoded['loop_ps'])
        struct.pack_into('>h', header, 0x46, encoded['loop_hist1'])
        struct.pack_into('>h', header, 0x48, encoded['loop_hist2'])
        struct.pack_into('>h', header, 0x4A, channels_hint)
        struct.pack_into('>H', header, 0x4C, block_size)
        return bytes(header)

    def _interleave_dsp_channels(self, left_bytes: bytes, right_bytes: bytes, block_size: int) -> bytes:
        out = bytearray()
        max_len = max(len(left_bytes), len(right_bytes))
        for pos in range(0, max_len, block_size):
            out += left_bytes[pos:pos + block_size]
            out += right_bytes[pos:pos + block_size]
        return bytes(out)

    def _encode_wav_to_dsp_bytes(self, wav_path: Path, force_mono: bool = False) -> bytes:
        sample_rate, channels, samples = self._load_wav_pcm16(wav_path)
        if force_mono and channels > 1:
            mono = np.round(samples.astype(np.int32).mean(axis=1)).astype(np.int16)
            enc = self._encode_pcm_channel_to_dsp(mono, sample_rate)
            return self._build_single_dsp_header(enc, 1, 8) + enc['adpcm_bytes']

        if channels == 1:
            enc = self._encode_pcm_channel_to_dsp(samples[:, 0], sample_rate)
            return self._build_single_dsp_header(enc, 1, 8) + enc['adpcm_bytes']

        left = self._encode_pcm_channel_to_dsp(samples[:, 0], sample_rate)
        right = self._encode_pcm_channel_to_dsp(samples[:, 1], sample_rate)
        if left['sample_count'] != right['sample_count'] or left['nibble_count'] != right['nibble_count'] or left['sample_rate'] != right['sample_rate']:
            raise ToolError('Stereo DSP channels encoded with mismatched metadata.')
        block_size = 8
        header1 = self._build_single_dsp_header(left, 2, block_size)
        header2 = self._build_single_dsp_header(right, 2, block_size)
        payload = self._interleave_dsp_channels(left['adpcm_bytes'], right['adpcm_bytes'], block_size)
        return header1 + header2 + payload

    def _downmix_wav_to_mono(self, wav_path: Path, out_path: Path):
        self.ensure_exists(wav_path)
        with wave.open(str(wav_path), "rb") as src:
            nch = src.getnchannels()
            sw = src.getsampwidth()
            fr = src.getframerate()
            nf = src.getnframes()
            comptype = src.getcomptype()
            if comptype != "NONE":
                raise ToolError("Only uncompressed PCM WAV files can be downmixed automatically.")
            frames = src.readframes(nf)
        if nch == 1:
            Path(out_path).write_bytes(Path(wav_path).read_bytes())
            return out_path
        if sw not in (1, 2, 3, 4):
            raise ToolError(f"Unsupported WAV sample width for downmix: {sw} byte(s).")

        bytes_per_frame = nch * sw
        if len(frames) % bytes_per_frame != 0:
            raise ToolError("WAV frame data size is not aligned to channel/sample width.")

        def read_sample(chunk: bytes) -> int:
            if sw == 1:
                return chunk[0] - 128
            if sw == 2:
                return int.from_bytes(chunk, "little", signed=True)
            if sw == 3:
                raw = int.from_bytes(chunk, "little", signed=False)
                if raw & 0x800000:
                    raw -= 0x1000000
                return raw
            return int.from_bytes(chunk, "little", signed=True)

        def write_sample(value: int) -> bytes:
            if sw == 1:
                value = max(-128, min(127, value))
                return bytes([(value + 128) & 0xFF])
            if sw == 2:
                value = max(-32768, min(32767, value))
                return int(value).to_bytes(2, "little", signed=True)
            if sw == 3:
                value = max(-8388608, min(8388607, value))
                if value < 0:
                    value += 0x1000000
                return int(value).to_bytes(3, "little", signed=False)
            value = max(-2147483648, min(2147483647, value))
            return int(value).to_bytes(4, "little", signed=True)

        out = bytearray()
        for i in range(0, len(frames), bytes_per_frame):
            frame = frames[i:i+bytes_per_frame]
            total = 0
            for ch in range(nch):
                start = ch * sw
                total += read_sample(frame[start:start+sw])
            mono = int(round(total / nch))
            out += write_sample(mono)

        with wave.open(str(out_path), "wb") as dst:
            dst.setnchannels(1)
            dst.setsampwidth(sw)
            dst.setframerate(fr)
            dst.writeframes(bytes(out))
        return out_path

    def encode_wav_to_mono_dsp(self, wav_path: Path, out_path: Path):
        self.ensure_exists(wav_path)
        data = self._encode_wav_to_dsp_bytes(wav_path, force_mono=True)
        Path(out_path).write_bytes(data)
        return out_path

    def wrap_wav_into_fsb_auto(self, template_fsb: Path, wav_path: Path, out_path: Path):
        self.ensure_exists(template_fsb)
        self.ensure_exists(wav_path)
        info = self.inspect_fsb_template(template_fsb)
        with tempfile.TemporaryDirectory() as td:
            dsp_path = Path(td) / "auto_wrap.dsp"
            if info["channels"] == 1:
                self.encode_wav_to_mono_dsp(wav_path, dsp_path)
                mode_note = "template is mono, so the WAV was downmixed before DSP encoding"
            elif info["channels"] == 2:
                self.encode_wav_to_dsp(wav_path, dsp_path)
                mode_note = "template is stereo, so the WAV was encoded as stereo DSP"
            else:
                raise ToolError(f"Unsupported template channel count for auto-wrap: {info['channels']}")
            self.wrap_dsp_into_fsb(template_fsb, dsp_path, out_path)
        return out_path, mode_note

    def inspect_fsb_template(self, fsb_path: Path):
        self.ensure_exists(fsb_path)
        blob = fsb_path.read_bytes()
        meta = self._parse_fsb_header(blob)
        chunks = []
        type_names = {1:"CHANNELS",2:"FREQUENCY",3:"LOOP",7:"DSPCOEFF"}
        for chunk in self._iter_sample_chunks(meta["sample_header"]):
            chunks.append({
                "type": chunk["type"],
                "name": type_names.get(chunk["type"], f"TYPE_{chunk['type']}"),
                "size": chunk["size"],
            })
        return {
            "mode": meta["mode"],
            "channels": meta["channels"],
            "sample_header_size": meta["sample_header_size"],
            "data_size": meta["data_size"],
            "chunks": chunks,
        }

    def decode_to_wav(self, in_path: Path, out_path: Path):
        self.ensure_exists(self.cvt_exe, "Converter")
        self.ensure_exists(in_path)
        self.run_process([str(self.cvt_exe), "-o", str(out_path), str(in_path)])
        return out_path

    def encode_wav_to_dsp(self, wav_path: Path, out_path: Path):
        self.ensure_exists(wav_path)
        data = self._encode_wav_to_dsp_bytes(wav_path, force_mono=False)
        Path(out_path).write_bytes(data)
        return out_path

    def get_metadata(self, combined_audio_path: Path):
        parsed = self.parse_combined_audio_table(combined_audio_path)
        counts = self.count_specific_bytes(combined_audio_path)
        sizes = [entry.size for entry in parsed['entries']]
        return {
            'header_length': parsed['header_length'],
            'audio_files': parsed['entry_count'],
            'min_segment_size': min(sizes) if sizes else 0,
            'max_segment_size': max(sizes) if sizes else 0,
            **counts,
        }

    def inspect_combined_audio(self, combined_audio_path: Path):
        parsed = self.parse_combined_audio_table(combined_audio_path)
        rows = []
        for entry in parsed['entries']:
            rows.append({
                'table_index': entry.table_index,
                'physical_index': entry.physical_index,
                'sound_id': entry.sound_id,
                'offset': entry.offset,
                'size': entry.size,
                'end_offset': entry.end_offset,
                'fsb_name': entry.fsb_name,
            })
        return {
            'entry_count': parsed['entry_count'],
            'header_length': parsed['header_length'],
            'file_size': parsed['file_size'],
            'rows': rows,
        }

    def count_specific_bytes(self, file_path: Path):
        data = Path(file_path).read_bytes()
        position = 0
        counts = {
            "gcadpcm": 0,
            "gcadpcm_interleaved": 0,
            "pcm8": 0,
            "pcm16": 0,
            "imafmod": 0,
            "celt_or_other": 0,
        }
        while True:
            position = data.find(b"FSB5", position)
            if position == -1:
                break
            mode_pos = position + 4 + 20
            if mode_pos < len(data):
                value = data[mode_pos]
                if value == 0x06:
                    counts["gcadpcm"] += 1
                    inter_pos = position + 4 + 0x20
                    if inter_pos < len(data) and data[inter_pos] == 0x02:
                        counts["gcadpcm_interleaved"] += 1
                elif value == 0x01:
                    counts["pcm8"] += 1
                elif value == 0x02:
                    counts["pcm16"] += 1
                elif value == 0x07:
                    counts["imafmod"] += 1
                else:
                    counts["celt_or_other"] += 1
            position += 4
        return counts


class CAToolGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.backend = CAToolBackend()
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry("980x760")
        self.minsize(900, 680)
        self._build_ui()

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        title = ttk.Label(root, text=f"{APP_TITLE} v{APP_VERSION}", font=("Segoe UI", 16, "bold"))
        title.pack(anchor="w")
        ttk.Label(
            root,
            text="GUI frontend for CombinedAudio/FSB/DSP workflows, with Python WAV→DSP encoding, CombinedAudio table-aware rebuilds, and GCADPCM FSB wrapping.",
        ).pack(anchor="w", pady=(2, 10))

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        self.logs = tk.Text(root, height=12, wrap="word")
        self.logs.pack(fill="both", expand=False, pady=(10, 0))
        self.logs.configure(state="disabled")

        tab_extract = ttk.Frame(notebook, padding=10)
        tab_convert = ttk.Frame(notebook, padding=10)
        tab_wrap = ttk.Frame(notebook, padding=10)
        tab_info = ttk.Frame(notebook, padding=10)
        tab_archive = ttk.Frame(notebook, padding=10)
        notebook.add(tab_extract, text="Extract / Rebuild")
        notebook.add(tab_convert, text="Convert")
        notebook.add(tab_wrap, text="DSP → FSB")
        notebook.add(tab_info, text="Inspect")
        notebook.add(tab_archive, text="CombinedAudio Table")

        self._build_extract_tab(tab_extract)
        self._build_convert_tab(tab_convert)
        self._build_wrap_tab(tab_wrap)
        self._build_info_tab(tab_info)
        self._build_archive_tab(tab_archive)

    def log(self, text: str):
        self.logs.configure(state="normal")
        self.logs.insert("end", text.rstrip() + "\n")
        self.logs.see("end")
        self.logs.configure(state="disabled")

    def run_action(self, title, callback):
        try:
            result = callback()
            if result:
                self.log(f"[{title}] {result}")
        except Exception as exc:
            self.log(f"[{title}] ERROR: {exc}")
            traceback.print_exc()
            messagebox.showerror(title, str(exc))

    def add_path_row(self, parent, row, label, var, filetypes=(("All Files", "*.*"),), directory=False, save=False, default_ext=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        def browse():
            if directory:
                value = filedialog.askdirectory()
            elif save:
                value = filedialog.asksaveasfilename(defaultextension=default_ext, filetypes=filetypes)
            else:
                value = filedialog.askopenfilename(filetypes=filetypes)
            if value:
                var.set(value)
        ttk.Button(parent, text="Browse...", command=browse).grid(row=row, column=2, pady=4, padx=(8, 0))

    def _build_extract_tab(self, tab):
        tab.columnconfigure(1, weight=1)
        self.ca_path = tk.StringVar()
        self.extract_dir = tk.StringVar(value=str(resource_path("out_path")))
        self.seg_dir = tk.StringVar(value=str(resource_path("out_path")))
        self.rebuild_out = tk.StringVar(value=str(resource_path("ModifiedCombinedAudio.bin")))
        self.rename_one = tk.StringVar()

        self.add_path_row(tab, 0, "CombinedAudio.bin", self.ca_path, filetypes=(("BIN Files", "*.bin"), ("All Files", "*.*")))
        self.add_path_row(tab, 1, "Extract folder", self.extract_dir, directory=True)
        ttk.Button(tab, text="Extract all FSB segments", command=lambda: self.run_action("Extract CombinedAudio", self._extract_combined)).grid(row=2, column=1, sticky="w", pady=(4, 10))
        ttk.Button(tab, text="Save header_data.bin", command=lambda: self.run_action("Extract Header", self._collect_header)).grid(row=2, column=2, sticky="e", pady=(4, 10))

        ttk.Separator(tab, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew", pady=10)
        self.add_path_row(tab, 4, "Segment folder", self.seg_dir, directory=True)
        self.add_path_row(tab, 5, "Rebuild output", self.rebuild_out, filetypes=(("BIN Files", "*.bin"),), save=True, default_ext=".bin")
        ttk.Button(tab, text="Rebuild CombinedAudio.bin", command=lambda: self.run_action("Rebuild CombinedAudio", self._rebuild_combined)).grid(row=6, column=1, sticky="w", pady=(4, 10))
        ttk.Button(tab, text="Rename all segment_*.fsb", command=lambda: self.run_action("Rename All Segments", self._rename_all_segments)).grid(row=6, column=2, sticky="e", pady=(4, 10))

        ttk.Separator(tab, orient="horizontal").grid(row=7, column=0, columnspan=3, sticky="ew", pady=10)
        self.add_path_row(tab, 8, "Single FSB segment", self.rename_one, filetypes=(("FSB Files", "*.fsb"), ("All Files", "*.*")))
        ttk.Button(tab, text="Show embedded segment name", command=lambda: self.run_action("Find Segment Name", self._show_segment_name)).grid(row=9, column=1, sticky="w")
        ttk.Button(tab, text="Rename this segment", command=lambda: self.run_action("Rename Segment", self._rename_one_segment)).grid(row=9, column=2, sticky="e")

    def _build_convert_tab(self, tab):
        tab.columnconfigure(1, weight=1)
        self.decode_in = tk.StringVar()
        self.decode_out = tk.StringVar()
        self.encode_in = tk.StringVar()
        self.encode_out = tk.StringVar()
        self.raw_fsb = tk.StringVar()
        self.raw_dsp = tk.StringVar()

        self.add_path_row(tab, 0, "Decode input (.fsb or .dsp)", self.decode_in, filetypes=(("Audio Files", "*.fsb *.dsp"), ("All Files", "*.*")))
        self.add_path_row(tab, 1, "Decode output (.wav)", self.decode_out, filetypes=(("WAV Files", "*.wav"),), save=True, default_ext=".wav")
        ttk.Button(tab, text="Decode to WAV", command=lambda: self.run_action("Decode to WAV", self._decode_to_wav)).grid(row=2, column=1, sticky="w", pady=(4, 10))

        ttk.Separator(tab, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew", pady=10)
        self.add_path_row(tab, 4, "Encode input (.wav)", self.encode_in, filetypes=(("WAV Files", "*.wav *.wave"), ("All Files", "*.*")))
        self.add_path_row(tab, 5, "Encode output (.dsp)", self.encode_out, filetypes=(("DSP Files", "*.dsp"),), save=True, default_ext=".dsp")
        ttk.Button(tab, text="Encode WAV to DSP", command=lambda: self.run_action("Encode WAV to DSP", self._encode_to_dsp)).grid(row=6, column=1, sticky="w", pady=(4, 10))
        ttk.Button(tab, text="Encode WAV to Mono DSP", command=lambda: self.run_action("Encode WAV to Mono DSP", self._encode_to_mono_dsp)).grid(row=6, column=2, sticky="e", pady=(4, 10))

        ttk.Separator(tab, orient="horizontal").grid(row=7, column=0, columnspan=3, sticky="ew", pady=10)
        self.add_path_row(tab, 8, "FSB for raw extract", self.raw_fsb, filetypes=(("FSB Files", "*.fsb"), ("All Files", "*.*")))
        self.add_path_row(tab, 9, "DSP for raw extract", self.raw_dsp, filetypes=(("DSP Files", "*.dsp"), ("All Files", "*.*")))
        ttk.Button(tab, text="Extract raw payload from FSB", command=lambda: self.run_action("Extract Raw FSB Payload", self._extract_raw_fsb)).grid(row=10, column=1, sticky="w")
        ttk.Button(tab, text="Extract raw payload from DSP", command=lambda: self.run_action("Extract Raw DSP Payload", self._extract_raw_dsp)).grid(row=10, column=2, sticky="e")

    def _build_wrap_tab(self, tab):
        tab.columnconfigure(1, weight=1)
        self.template_fsb = tk.StringVar()
        self.wrap_dsp = tk.StringVar()
        self.wrap_wav = tk.StringVar()
        self.wrap_out = tk.StringVar()
        note = (
            "Use a GCADPCM FSB from the target game as the template. The tool updates the FSB sample count, frequency, loop points, "
            "DSP coefficient block, file-level data size, and replaces the raw ADPCM payload."
        )
        ttk.Label(tab, text=note, wraplength=820, justify="left").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self.add_path_row(tab, 1, "Template FSB (.fsb)", self.template_fsb, filetypes=(("FSB Files", "*.fsb"), ("All Files", "*.*")))
        self.add_path_row(tab, 2, "Encoded DSP (.dsp)", self.wrap_dsp, filetypes=(("DSP Files", "*.dsp"), ("All Files", "*.*")))
        self.add_path_row(tab, 3, "Source WAV for auto-wrap (.wav)", self.wrap_wav, filetypes=(("WAV Files", "*.wav *.wave"), ("All Files", "*.*")))
        self.add_path_row(tab, 4, "Output FSB (.fsb)", self.wrap_out, filetypes=(("FSB Files", "*.fsb"),), save=True, default_ext=".fsb")
        ttk.Button(tab, text="Wrap DSP into template FSB", command=lambda: self.run_action("DSP → FSB", self._wrap_dsp_into_fsb)).grid(row=5, column=1, sticky="w", pady=(8, 0))
        ttk.Button(tab, text="Auto-wrap WAV into template FSB", command=lambda: self.run_action("WAV → FSB", self._wrap_wav_into_fsb_auto)).grid(row=5, column=2, sticky="e", pady=(8, 0))
        ttk.Button(tab, text="Autofill output name", command=self._autofill_wrap_name).grid(row=6, column=2, sticky="e", pady=(8, 0))

    def _build_info_tab(self, tab):
        tab.columnconfigure(1, weight=1)
        self.meta_path = tk.StringVar()
        self.dsp_info_path = tk.StringVar()
        self.fsb_info_path = tk.StringVar()
        self.add_path_row(tab, 0, "CombinedAudio.bin", self.meta_path, filetypes=(("BIN Files", "*.bin"), ("All Files", "*.*")))
        ttk.Button(tab, text="Get CombinedAudio metadata", command=lambda: self.run_action("CombinedAudio Metadata", self._show_metadata)).grid(row=1, column=1, sticky="w", pady=(4, 12))
        self.add_path_row(tab, 2, "DSP file", self.dsp_info_path, filetypes=(("DSP Files", "*.dsp"), ("All Files", "*.*")))
        ttk.Button(tab, text="Read DSP header", command=lambda: self.run_action("DSP Header", self._show_dsp_header)).grid(row=3, column=1, sticky="w", pady=(4, 12))
        self.add_path_row(tab, 4, "FSB template", self.fsb_info_path, filetypes=(("FSB Files", "*.fsb"), ("All Files", "*.*")))
        ttk.Button(tab, text="Inspect FSB template", command=lambda: self.run_action("FSB Template", self._show_fsb_template)).grid(row=5, column=1, sticky="w", pady=(4, 0))

    def _build_archive_tab(self, tab):
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(2, weight=1)
        self.archive_path = tk.StringVar()
        self.add_path_row(tab, 0, 'CombinedAudio.bin', self.archive_path, filetypes=(("BIN Files", "*.bin"), ("All Files", "*.*")))
        btns = ttk.Frame(tab)
        btns.grid(row=1, column=0, columnspan=3, sticky='w', pady=(4, 8))
        ttk.Button(btns, text='Load CombinedAudio table', command=lambda: self.run_action('CombinedAudio Table', self._load_archive_table)).pack(side='left')
        ttk.Button(btns, text='Copy selected row', command=self._copy_archive_row).pack(side='left', padx=(8, 0))
        ttk.Button(btns, text='Copy all rows as TSV', command=self._copy_all_archive_rows).pack(side='left', padx=(8, 0))

        columns = ('table_index', 'physical_index', 'sound_id', 'offset_hex', 'size', 'end_hex', 'fsb_name')
        self.archive_tree = ttk.Treeview(tab, columns=columns, show='headings', height=18)
        headings = {
            'table_index': 'Table #',
            'physical_index': 'Segment #',
            'sound_id': 'Sound ID',
            'offset_hex': 'Offset',
            'size': 'Size',
            'end_hex': 'End',
            'fsb_name': 'FSB Name',
        }
        widths = {
            'table_index': 70,
            'physical_index': 80,
            'sound_id': 110,
            'offset_hex': 110,
            'size': 90,
            'end_hex': 110,
            'fsb_name': 260,
        }
        for col in columns:
            self.archive_tree.heading(col, text=headings[col])
            self.archive_tree.column(col, width=widths[col], anchor='w', stretch=(col == 'fsb_name'))

        yscroll = ttk.Scrollbar(tab, orient='vertical', command=self.archive_tree.yview)
        xscroll = ttk.Scrollbar(tab, orient='horizontal', command=self.archive_tree.xview)
        self.archive_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.archive_tree.grid(row=2, column=0, columnspan=2, sticky='nsew')
        yscroll.grid(row=2, column=2, sticky='ns')
        xscroll.grid(row=3, column=0, columnspan=2, sticky='ew')

        self.archive_summary = tk.Text(tab, height=8, wrap='word')
        self.archive_summary.grid(row=4, column=0, columnspan=3, sticky='ew', pady=(8, 0))
        self.archive_summary.configure(state='disabled')

    def _set_archive_summary(self, text: str):
        self.archive_summary.configure(state='normal')
        self.archive_summary.delete('1.0', 'end')
        self.archive_summary.insert('1.0', text)
        self.archive_summary.configure(state='disabled')

    def _load_archive_table(self):
        info = self.backend.inspect_combined_audio(Path(self.archive_path.get()))
        for item in self.archive_tree.get_children():
            self.archive_tree.delete(item)
        for row in sorted(info['rows'], key=lambda r: r['table_index']):
            self.archive_tree.insert('', 'end', values=(
                row['table_index'],
                row['physical_index'],
                row['sound_id'],
                f"0x{row['offset']:X}",
                row['size'],
                f"0x{row['end_offset']:X}",
                row['fsb_name'],
            ))
        summary = (
            f"Entry count: {info['entry_count']}\n"
            f"Header length: 0x{info['header_length']:X} ({info['header_length']})\n"
            f"File size: 0x{info['file_size']:X} ({info['file_size']})\n"
            f"Rows loaded: {len(info['rows'])}\n"
            "Columns: table index, physical FSB order (segment index), sound ID, offset, size, end offset, embedded FSB name."
        )
        self._set_archive_summary(summary)
        return f"Loaded {len(info['rows'])} CombinedAudio entries."

    def _copy_archive_row(self):
        selected = self.archive_tree.selection()
        if not selected:
            raise ToolError('Select a row in the CombinedAudio Table tab first.')
        values = self.archive_tree.item(selected[0], 'values')
        text = '\t'.join(str(v) for v in values)
        self.clipboard_clear()
        self.clipboard_append(text)
        return 'Copied selected CombinedAudio row to clipboard.'

    def _copy_all_archive_rows(self):
        rows = []
        headers = ['Table #', 'Segment #', 'Sound ID', 'Offset', 'Size', 'End', 'FSB Name']
        rows.append('\t'.join(headers))
        for item in self.archive_tree.get_children():
            values = self.archive_tree.item(item, 'values')
            rows.append('\t'.join(str(v) for v in values))
        text = '\n'.join(rows)
        self.clipboard_clear()
        self.clipboard_append(text)
        return 'Copied all CombinedAudio rows to clipboard as TSV.'

    def _extract_combined(self):
        count = self.backend.extract_combined_audio(Path(self.ca_path.get()), Path(self.extract_dir.get()))
        return f"Extracted {count} FSB segments to: {self.extract_dir.get()}"

    def _collect_header(self):
        out = self.backend.collect_header(Path(self.ca_path.get()), Path(self.extract_dir.get()))
        return f"Saved header to: {out}"

    def _rebuild_combined(self):
        out = self.backend.rebuild_combined_audio(Path(self.seg_dir.get()), Path(self.rebuild_out.get()))
        return f"Rebuilt file: {out}"

    def _show_segment_name(self):
        name = self.backend.get_segment_name(Path(self.rename_one.get()))
        if not name:
            raise ToolError("No embedded name was found in this FSB segment.")
        messagebox.showinfo("Embedded Segment Name", name)
        return f"Embedded name: {name}"

    def _rename_one_segment(self):
        out = self.backend.rename_segment(Path(self.rename_one.get()))
        self.rename_one.set(str(out))
        return f"Renamed to: {out.name}"

    def _rename_all_segments(self):
        items = self.backend.rename_all_segments(Path(self.seg_dir.get()))
        if not items:
            return "No segment files were renamed."
        preview = "\n".join(f"{old} -> {new}" for old, new in items[:20])
        messagebox.showinfo("Rename Results", preview if len(items) <= 20 else preview + f"\n... and {len(items) - 20} more")
        return f"Renamed {len(items)} segment files."

    def _decode_to_wav(self):
        out = Path(self.decode_out.get())
        if not str(out).strip():
            out = Path(self.decode_in.get()).with_suffix(".wav")
            self.decode_out.set(str(out))
        result = self.backend.decode_to_wav(Path(self.decode_in.get()), out)
        return f"Decoded to: {result}"

    def _encode_to_dsp(self):
        out = Path(self.encode_out.get())
        if not str(out).strip():
            out = Path(self.encode_in.get()).with_suffix(".dsp")
            self.encode_out.set(str(out))
        result = self.backend.encode_wav_to_dsp(Path(self.encode_in.get()), out)
        return f"Encoded to: {result}"

    def _extract_raw_fsb(self):
        out = self.backend.extract_raw_from_fsb(Path(self.raw_fsb.get()))
        return f"Wrote raw FSB payload: {out}"

    def _extract_raw_dsp(self):
        out = self.backend.extract_raw_from_dsp(Path(self.raw_dsp.get()))
        return f"Wrote raw DSP payload: {out}"

    def _autofill_wrap_name(self):
        tpl = self.template_fsb.get().strip()
        dsp = self.wrap_dsp.get().strip()
        if tpl and dsp:
            out = Path(tpl).with_name(f"{Path(tpl).stem}_{Path(dsp).stem}.fsb")
        elif tpl:
            out = Path(tpl).with_name(f"{Path(tpl).stem}_wrapped.fsb")
        else:
            out = resource_path("wrapped_output.fsb")
        self.wrap_out.set(str(out))

    def _wrap_dsp_into_fsb(self):
        out = Path(self.wrap_out.get())
        if not str(out).strip():
            self._autofill_wrap_name()
            out = Path(self.wrap_out.get())
        result = self.backend.wrap_dsp_into_fsb(Path(self.template_fsb.get()), Path(self.wrap_dsp.get()), out)
        return f"Built wrapped FSB: {result}"

    def _wrap_wav_into_fsb_auto(self):
        out = Path(self.wrap_out.get())
        if not str(out).strip():
            self._autofill_wrap_name()
            out = Path(self.wrap_out.get())
        result, note = self.backend.wrap_wav_into_fsb_auto(Path(self.template_fsb.get()), Path(self.wrap_wav.get()), out)
        return f"Built wrapped FSB: {result} ({note})"

    def _encode_to_mono_dsp(self):
        out = Path(self.encode_out.get())
        if not str(out).strip():
            source = Path(self.encode_in.get())
            out = source.with_suffix(".dsp")
            self.encode_out.set(str(out))
        result = self.backend.encode_wav_to_mono_dsp(Path(self.encode_in.get()), out)
        return f"Encoded mono DSP: {result}"

    def _show_fsb_template(self):
        info = self.backend.inspect_fsb_template(Path(self.fsb_info_path.get()))
        lines = [
            f"Mode: {info['mode']}",
            f"Channels: {info['channels']}",
            f"Sample header size: {info['sample_header_size']}",
            f"Data size: {info['data_size']}",
            "Chunks:",
        ]
        for chunk in info['chunks']:
            lines.append(f"  - {chunk['name']} (type {chunk['type']}): {chunk['size']} bytes")
        text = "\n".join(lines)
        messagebox.showinfo("FSB Template", text)
        return text

    def _show_metadata(self):
        info = self.backend.get_metadata(Path(self.meta_path.get()))
        text = (
            f"Header length: {info['header_length']}\n"
            f"Audio files: {info['audio_files']}\n"
            f"Smallest segment: {info['min_segment_size']} bytes\n"
            f"Largest segment: {info['max_segment_size']} bytes\n"
            f"GCADPCM: {info['gcadpcm']}\n"
            f"GCADPCM interleaved: {info['gcadpcm_interleaved']}\n"
            f"GCADPCM flat: {info['gcadpcm'] - info['gcadpcm_interleaved']}\n"
            f"PCM8: {info['pcm8']}\n"
            f"PCM16: {info['pcm16']}\n"
            f"IMAFMOD: {info['imafmod']}\n"
            f"CELT/other: {info['celt_or_other']}"
        )
        messagebox.showinfo("CombinedAudio Metadata", text)
        return text

    def _show_dsp_header(self):
        dsp = self.backend.read_dsp_header(Path(self.dsp_info_path.get()))
        text = (
            f"Sample count: {dsp.sample_count}\n"
            f"Nibble count: {dsp.nibble_count}\n"
            f"Sample rate: {dsp.sample_rate}\n"
            f"Loop flag: {dsp.loop_flag}\n"
            f"Format: {dsp.fmt}\n"
            f"Loop start: {dsp.loop_start}\n"
            f"Loop end: {dsp.loop_end}\n"
            f"Channels: {dsp.channels}\n"
            f"Data offset: 0x{dsp.data_offset:X}"
        )
        messagebox.showinfo("DSP Header", text)
        return text


def main():
    app = CAToolGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
