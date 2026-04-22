import io, json, os, atexit, threading, struct, subprocess
import tempfile, traceback, wave, copy, shutil, sys
from tkinter import ttk, filedialog, messagebox
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
import numpy as np

try:
    import winsound
except Exception:
    winsound = None

APP_TITLE = "Cracko298's CATool GUI"
APP_VERSION = "2.5.0"
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
    offset: int
    size: int
    end_offset: int
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

        blob[meta["sample_header_off"]:meta["sample_header_off"] + meta["sample_header_size"]] = sample_header

        struct.pack_into("<I", blob, 0x14, len(payload))

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

    def _dsp_nibble_to_signed(self, nibble: int) -> int:
        return nibble - 16 if nibble & 0x8 else nibble

    def _decode_dsp_channel_bytes(self, payload: bytes, sample_count: int, coeff_pairs, hist1: int = 0, hist2: int = 0) -> np.ndarray:
        out = np.zeros(sample_count, dtype=np.int16)
        out_index = 0
        pos = 0
        while out_index < sample_count and pos + 8 <= len(payload):
            header = payload[pos]
            pos += 1
            pred_idx = (header >> 4) & 0x0F
            scale_shift = header & 0x0F
            if pred_idx >= len(coeff_pairs):
                pred_idx = 0
            coef1, coef2 = coeff_pairs[pred_idx]
            data = payload[pos:pos + 7]
            pos += 7
            nibbles = []
            for byte_value in data:
                nibbles.append(self._dsp_nibble_to_signed((byte_value >> 4) & 0x0F))
                nibbles.append(self._dsp_nibble_to_signed(byte_value & 0x0F))
            for nibble in nibbles:
                if out_index >= sample_count:
                    break
                sample = self._decode_dsp_sample(nibble, scale_shift, coef1, coef2, hist1, hist2)
                out[out_index] = sample
                hist2, hist1 = hist1, sample
                out_index += 1
        return out

    def _coeff_blob_to_pairs(self, coeff_blob: bytes, channels: int):
        per_channel = 16 * 2
        if len(coeff_blob) not in (46, 92) and len(coeff_blob) < channels * per_channel:
            raise ToolError(f"Unsupported DSP coefficient blob size: {len(coeff_blob)}")
        pairs_by_channel = []
        for ch in range(channels):
            start = ch * 46 if len(coeff_blob) >= (ch + 1) * 46 else ch * per_channel
            chunk = coeff_blob[start:start + 46]
            if len(chunk) < per_channel:
                raise ToolError('DSP coefficient blob is too small for the reported channel count.')
            pairs = [struct.unpack_from('>hh', chunk, i * 4) for i in range(8)]
            pairs_by_channel.append(pairs)
        return pairs_by_channel

    def _wav_bytes_from_pcm16(self, pcm: np.ndarray, sample_rate: int) -> bytes:
        if pcm.ndim == 1:
            channels = 1
            frame_bytes = pcm.astype('<i2').tobytes()
        else:
            channels = pcm.shape[1]
            frame_bytes = pcm.astype('<i2').tobytes()
        bio = io.BytesIO()
        with wave.open(bio, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(frame_bytes)
        return bio.getvalue()

    def _wav_bytes_from_pcm8(self, pcm: bytes, sample_rate: int, channels: int) -> bytes:
        bio = io.BytesIO()
        with wave.open(bio, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(1)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
        return bio.getvalue()

    def _extract_fsb_sample_metadata(self, fsb_bytes: bytes):
        meta = self._parse_fsb_header(fsb_bytes)
        sample_mode = struct.unpack_from('<Q', meta['sample_header'], 0)[0]
        sample_count = (sample_mode >> 34) & 0x3FFFFFFF
        channels = meta['channels']
        sample_rate = None
        for chunk in self._iter_sample_chunks(meta['sample_header']):
            ctype = chunk['type']
            cstart = chunk['data_offset']
            if ctype == 1 and chunk['size'] >= 1:
                channels = meta['sample_header'][cstart]
            elif ctype == 2 and chunk['size'] == 4:
                sample_rate = struct.unpack_from('<I', meta['sample_header'], cstart)[0]
        if sample_count <= 0:
            raise ToolError('FSB sample count is invalid or missing.')
        if sample_rate is None or sample_rate <= 0:
            raise ToolError('FSB frequency chunk is missing or invalid.')
        payload = fsb_bytes[meta['data_off']:meta['data_off'] + meta['data_size']]
        if len(payload) < meta['data_size']:
            raise ToolError('FSB payload is truncated.')
        return {
            'mode': meta['mode'],
            'sample_count': sample_count,
            'sample_rate': sample_rate,
            'channels': channels,
            'payload': payload,
            'meta': meta,
        }

    def _decode_fadpcm_channel_bytes(self, channel_payload: bytes, sample_count: int) -> np.ndarray:
        frame_size = 0x8C
        samples_per_frame = (frame_size - 0x0C) * 2
        out = np.zeros(sample_count, dtype=np.int16)
        out_index = 0
        coef_table = (
            (0, 0),
            (60, 0),
            (122, 60),
            (115, 52),
            (98, 55),
            (0, 0),
            (0, 0),
            (0, 0),
        )
        for frame_pos in range(0, len(channel_payload), frame_size):
            if out_index >= sample_count:
                break
            frame = channel_payload[frame_pos:frame_pos + frame_size]
            if len(frame) < frame_size:
                break
            coefs = struct.unpack_from('<I', frame, 0x00)[0]
            shifts = struct.unpack_from('<I', frame, 0x04)[0]
            hist1 = struct.unpack_from('<h', frame, 0x08)[0]
            hist2 = struct.unpack_from('<h', frame, 0x0A)[0]
            for i in range(8):
                index = ((coefs >> (i * 4)) & 0x0F) % 0x07
                shift = (shifts >> (i * 4)) & 0x0F
                coef1, coef2 = coef_table[index]
                shift = 22 - shift
                for j in range(4):
                    nibbles = struct.unpack_from('<I', frame, 0x0C + (0x10 * i) + (0x04 * j))[0]
                    for k in range(8):
                        if out_index >= sample_count:
                            break
                        sample = (nibbles >> (k * 4)) & 0x0F
                        sample = (sample << 28) & 0xFFFFFFFF
                        if sample & 0x80000000:
                            sample -= 0x100000000
                        sample = sample >> shift
                        sample = (sample - hist2 * coef2 + hist1 * coef1) >> 6
                        sample = self._dsp_clamp16(sample)
                        out[out_index] = sample
                        out_index += 1
                        hist2, hist1 = hist1, sample
                    if out_index >= sample_count:
                        break
                if out_index >= sample_count:
                    break
        return out

    def _decode_fadpcm_fsb_to_wav_bytes(self, fsb_bytes: bytes) -> bytes:
        info = self._extract_fsb_sample_metadata(fsb_bytes)
        channels = info['channels']
        sample_rate = info['sample_rate']
        sample_count = info['sample_count']
        payload = info['payload']
        frame_size = 0x8C
        samples_per_frame = (frame_size - 0x0C) * 2
        frames_per_channel = (sample_count + samples_per_frame - 1) // samples_per_frame
        if channels < 1:
            raise ToolError('FADPCM channel count is invalid.')
        expected_min = frames_per_channel * frame_size * channels
        if len(payload) < min(expected_min, frame_size * channels):
            raise ToolError('FADPCM payload is too small for the reported sample count/channels.')
        if channels == 1:
            pcm = self._decode_fadpcm_channel_bytes(payload, sample_count)
            return self._wav_bytes_from_pcm16(pcm, sample_rate)
        if channels == 2:
            left_parts = []
            right_parts = []
            for frame_index in range(frames_per_channel):
                base = frame_index * frame_size * 2
                left_parts.append(payload[base:base + frame_size])
                right_parts.append(payload[base + frame_size:base + (frame_size * 2)])
            left_pcm = self._decode_fadpcm_channel_bytes(b''.join(left_parts), sample_count)
            right_pcm = self._decode_fadpcm_channel_bytes(b''.join(right_parts), sample_count)
            stereo = np.column_stack((left_pcm, right_pcm))
            return self._wav_bytes_from_pcm16(stereo, sample_rate)
        raise ToolError(f'Only mono and stereo FADPCM FSB files are supported right now. Found {channels} channels.')

    def _decode_pcm_fsb_to_wav_bytes(self, fsb_bytes: bytes) -> bytes:
        info = self._extract_fsb_sample_metadata(fsb_bytes)
        mode = info['mode']
        channels = info['channels']
        sample_rate = info['sample_rate']
        payload = info['payload']
        sample_count = info['sample_count']
        if mode == 1:
            expected = sample_count * channels
            return self._wav_bytes_from_pcm8(payload[:expected], sample_rate, channels)
        if mode == 2:
            expected = sample_count * channels * 2
            pcm = payload[:expected]
            return self._wav_bytes_from_pcm16(np.frombuffer(pcm, dtype='<i2').reshape(-1, channels) if channels > 1 else np.frombuffer(pcm, dtype='<i2'), sample_rate)
        if mode == 16:
            return self._decode_fadpcm_fsb_to_wav_bytes(fsb_bytes)
        raise ToolError(f'Unsupported PCM-like FSB mode: {mode}')

    def decode_dsp_bytes_to_wav_bytes(self, dsp_bytes: bytes) -> bytes:
        if len(dsp_bytes) < DSP_HEADER_SIZE:
            raise ToolError('DSP data is smaller than the required 0x60-byte header.')
        h1 = self._parse_single_dsp_header(dsp_bytes[:DSP_HEADER_SIZE])
        channels = 1
        data_offset = DSP_HEADER_SIZE
        coeff_blobs = [h1['raw_header'][0x1C:0x4A]]
        initial_states = [(struct.unpack_from('>h', h1['raw_header'], 0x40)[0], struct.unpack_from('>h', h1['raw_header'], 0x42)[0])]
        if len(dsp_bytes) >= DSP_HEADER_SIZE * 2:
            try:
                h2 = self._parse_single_dsp_header(dsp_bytes[DSP_HEADER_SIZE:DSP_HEADER_SIZE * 2])
            except ToolError:
                h2 = None
            if h2 and all(h1[k] == h2[k] for k in ('sample_count', 'nibble_count', 'sample_rate', 'loop_flag', 'fmt')):
                channels = 2
                data_offset = DSP_HEADER_SIZE * 2
                coeff_blobs.append(h2['raw_header'][0x1C:0x4A])
                initial_states.append((struct.unpack_from('>h', h2['raw_header'], 0x40)[0], struct.unpack_from('>h', h2['raw_header'], 0x42)[0]))
        sample_count = h1['sample_count']
        sample_rate = h1['sample_rate']
        payload = dsp_bytes[data_offset:]
        frame_count = (sample_count + 13) // 14
        ch_payload_size = frame_count * 8
        pairs_by_channel = [self._coeff_blob_to_pairs(blob, 1)[0] for blob in coeff_blobs]
        if channels == 1:
            pcm = self._decode_dsp_channel_bytes(payload[:ch_payload_size], sample_count, pairs_by_channel[0], *initial_states[0])
            return self._wav_bytes_from_pcm16(pcm, sample_rate)
        left_parts = []
        right_parts = []
        for pos in range(0, len(payload), 16):
            left_parts.append(payload[pos:pos + 8])
            right_parts.append(payload[pos + 8:pos + 16])
        left_payload = b''.join(left_parts)[:ch_payload_size]
        right_payload = b''.join(right_parts)[:ch_payload_size]
        left_pcm = self._decode_dsp_channel_bytes(left_payload, sample_count, pairs_by_channel[0], *initial_states[0])
        right_pcm = self._decode_dsp_channel_bytes(right_payload, sample_count, pairs_by_channel[1], *initial_states[1])
        stereo = np.column_stack((left_pcm, right_pcm))
        return self._wav_bytes_from_pcm16(stereo, sample_rate)

    def _extract_fsb_decode_info(self, fsb_bytes: bytes):
        info = self._extract_fsb_sample_metadata(fsb_bytes)
        if info['mode'] != 6:
            raise ToolError(f"Only GCADPCM FSB files are supported by this decoder path. Found mode {info['mode']}.")
        coeff_blob = None
        meta = info['meta']
        for chunk in self._iter_sample_chunks(meta['sample_header']):
            ctype = chunk['type']
            cstart = chunk['data_offset']
            cend = chunk['data_end']
            if ctype == 7:
                coeff_blob = bytes(meta['sample_header'][cstart:cend])
        if coeff_blob is None:
            raise ToolError('FSB DSPCOEFF chunk is missing.')
        return {
            'sample_count': info['sample_count'],
            'sample_rate': info['sample_rate'],
            'channels': info['channels'],
            'coeff_blob': coeff_blob,
            'payload': info['payload'],
        }

    def decode_fsb_bytes_to_wav_bytes(self, fsb_bytes: bytes) -> bytes:
        if not fsb_bytes or fsb_bytes[:4] != b"FSB5":
            raise ToolError("Selected CombinedAudio entry is not a valid FSB5 segment.")
        meta = self._parse_fsb_header(fsb_bytes)
        if meta['mode'] in (1, 2, 16):
            return self._decode_pcm_fsb_to_wav_bytes(fsb_bytes)
        info = self._extract_fsb_decode_info(fsb_bytes)
        sample_count = info['sample_count']
        sample_rate = info['sample_rate']
        channels = info['channels']
        payload = info['payload']
        pairs_by_channel = self._coeff_blob_to_pairs(info['coeff_blob'], channels)
        frame_count = (sample_count + 13) // 14
        ch_payload_size = frame_count * 8
        if channels == 1:
            pcm = self._decode_dsp_channel_bytes(payload[:ch_payload_size], sample_count, pairs_by_channel[0])
            return self._wav_bytes_from_pcm16(pcm, sample_rate)
        if channels != 2:
            raise ToolError(f'Only mono and stereo GCADPCM FSB files are supported right now. Found {channels} channels.')
        left_parts = []
        right_parts = []
        for pos in range(0, len(payload), 16):
            left_parts.append(payload[pos:pos + 8])
            right_parts.append(payload[pos + 8:pos + 16])
        left_payload = b''.join(left_parts)[:ch_payload_size]
        right_payload = b''.join(right_parts)[:ch_payload_size]
        left_pcm = self._decode_dsp_channel_bytes(left_payload, sample_count, pairs_by_channel[0])
        right_pcm = self._decode_dsp_channel_bytes(right_payload, sample_count, pairs_by_channel[1])
        stereo = np.column_stack((left_pcm, right_pcm))
        return self._wav_bytes_from_pcm16(stereo, sample_rate)

    def decode_audio_to_wav_bytes(self, in_path: Path) -> bytes:
        self.ensure_exists(in_path)
        suffix = in_path.suffix.lower()
        data = in_path.read_bytes()
        if suffix == '.dsp':
            return self.decode_dsp_bytes_to_wav_bytes(data)
        if suffix == '.fsb':
            return self.decode_fsb_bytes_to_wav_bytes(data)
        if data[:4] == b'FSB5':
            return self.decode_fsb_bytes_to_wav_bytes(data)
        return self.decode_dsp_bytes_to_wav_bytes(data)

    def save_decoded_audio_to_wav(self, in_path: Path, out_path: Path):
        wav_bytes = self.decode_audio_to_wav_bytes(in_path)
        Path(out_path).write_bytes(wav_bytes)
        return Path(out_path)

    def _replace_combined_audio_entry_blob(self, combined_audio_path: Path, table_index: int, new_blob: bytes, output_path: Path = None):
        parsed = self.parse_combined_audio_table(combined_audio_path)
        if table_index < 0 or table_index >= len(parsed['entries']):
            raise ToolError(f'CombinedAudio table index out of range: {table_index}')
        if not new_blob.startswith(b'FSB5'):
            raise ToolError('Replacement data must be an FSB5 blob.')
        output_path = Path(output_path or combined_audio_path)
        physical_entries = list(parsed['entries_by_physical'])
        replacement_map = {entry.table_index: parsed['data'][entry.absolute_offset:entry.absolute_end_offset] for entry in parsed['entries']}
        replacement_map[table_index] = new_blob
        entries = [None] * parsed['entry_count']
        data_chunks = []
        current_offset = 0
        for entry in physical_entries:
            blob = replacement_map[entry.table_index]
            current_offset = self._align_up(current_offset)
            entries[entry.table_index] = (entry.sound_id, current_offset, len(blob))
            data_chunks.append((current_offset, blob))
            current_offset += len(blob)
        header = bytearray(4 + (parsed['entry_count'] * 12))
        struct.pack_into('<I', header, 0, parsed['entry_count'])
        for idx, packed in enumerate(entries):
            sound_id, fsb_offset, fsb_size = packed
            struct.pack_into('<III', header, 4 + (idx * 12), sound_id, fsb_offset, fsb_size)
        out = bytearray(header)
        header_length = len(header)
        for fsb_offset, blob in data_chunks:
            absolute_offset = header_length + fsb_offset
            if len(out) < absolute_offset:
                out.extend(b'\x00' * (absolute_offset - len(out)))
            out.extend(blob)
        output_path.write_bytes(bytes(out))
        return output_path

    def build_replacement_fsb_from_source(self, template_fsb_bytes: bytes, replacement_path: Path) -> bytes:
        self.ensure_exists(replacement_path)
        suffix = replacement_path.suffix.lower()
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            template_path = td_path / 'template.fsb'
            template_path.write_bytes(template_fsb_bytes)
            if suffix == '.fsb':
                blob = replacement_path.read_bytes()
                if not blob.startswith(b'FSB5'):
                    raise ToolError('Selected replacement FSB is not a valid FSB5 file.')
                return blob
            if suffix in ('.wav', '.wave'):
                out_fsb = td_path / 'replacement.fsb'
                self.wrap_wav_into_fsb_auto(template_path, replacement_path, out_fsb)
                return out_fsb.read_bytes()
            if suffix == '.dsp':
                out_fsb = td_path / 'replacement.fsb'
                self.wrap_dsp_into_fsb(template_path, replacement_path, out_fsb)
                return out_fsb.read_bytes()
            raise ToolError('Replacement file must be .fsb, .wav, .wave, or .dsp')

    def replace_combined_audio_entry_from_file(self, combined_audio_path: Path, table_index: int, replacement_path: Path, output_path: Path = None):
        template_fsb = self.get_combined_audio_entry_fsb_bytes(combined_audio_path, table_index)
        new_blob = self.build_replacement_fsb_from_source(template_fsb, replacement_path)
        return self._replace_combined_audio_entry_blob(combined_audio_path, table_index, new_blob, output_path=output_path)

    def get_combined_audio_entry_fsb_bytes(self, combined_audio_path: Path, table_index: int) -> bytes:
        parsed = self.parse_combined_audio_table(combined_audio_path)
        if table_index < 0 or table_index >= len(parsed['entries']):
            raise ToolError(f"CombinedAudio table index out of range: {table_index}")
        entry = parsed['entries'][table_index]
        return parsed['data'][entry.absolute_offset:entry.absolute_end_offset]

    def get_combined_audio_entry_wav_bytes(self, combined_audio_path: Path, table_index: int) -> bytes:
        fsb_bytes = self.get_combined_audio_entry_fsb_bytes(combined_audio_path, table_index)
        return self.decode_fsb_bytes_to_wav_bytes(fsb_bytes)

    def decode_to_wav(self, in_path: Path, out_path: Path):
        return self.save_decoded_audio_to_wav(in_path, out_path)

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
        self._current_wav_bytes = None
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self._build_ui()
        self._lock_startup_window_size()

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

        tab_extract = ttk.Frame(notebook, padding=20)
        tab_convert = ttk.Frame(notebook, padding=20)
        tab_wrap = ttk.Frame(notebook, padding=20)
        tab_info = ttk.Frame(notebook, padding=20)
        tab_archive = ttk.Frame(notebook, padding=20)
        notebook.add(tab_archive, text="CombinedAudio Table/Editor")
        notebook.add(tab_extract, text="Extract / Rebuild")
        notebook.add(tab_wrap, text="WAV/DSP → FSB")
        notebook.add(tab_convert, text="Convert")
        notebook.add(tab_info, text="Inspect")
        

        self._build_extract_tab(tab_extract)
        self._build_convert_tab(tab_convert)
        self._build_wrap_tab(tab_wrap)
        self._build_info_tab(tab_info)
        self._build_archive_tab(tab_archive)

    def _lock_startup_window_size(self):
        width, height = 1700, 1000
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(width, max(1000, screen_w - 80))
        height = min(height, max(720, screen_h - 80))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(width, height)
        self.maxsize(width, height)
        self.resizable(False, False)

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
        tab.rowconfigure(3, weight=1)
        self.archive_path = tk.StringVar()
        self.archive_out_path = tk.StringVar()
        self.add_path_row(tab, 0, 'CombinedAudio.bin', self.archive_path, filetypes=(("BIN Files", "*.bin"), ("All Files", "*.*")))
        self.add_path_row(tab, 1, 'Replacement output (.bin, optional)', self.archive_out_path, filetypes=(("BIN Files", "*.bin"),), save=True, default_ext='.bin')
        btns = ttk.Frame(tab)
        btns.grid(row=2, column=0, columnspan=3, sticky='w', pady=(4, 8))
        ttk.Button(btns, text='Load CombinedAudio Table', command=lambda: self.run_action('CombinedAudio Table', self._load_archive_table)).pack(side='left')
        ttk.Button(btns, text='Play Selected FSB', command=lambda: self.run_action('Play Selected FSB', self._play_archive_selection)).pack(side='left', padx=(8, 0))
        ttk.Button(btns, text='Stop Playback', command=lambda: self.run_action('Stop Playback', self._stop_playback)).pack(side='left', padx=(8, 0))
        ttk.Button(btns, text='Replace Selected SFX', command=lambda: self.run_action('Replace Selected Sound', self._replace_archive_selection)).pack(side='left', padx=(8, 0))
        ttk.Button(btns, text='Reload Table', command=lambda: self.run_action('Reload Table', self._reload_archive_table)).pack(side='left', padx=(8, 0))
        ttk.Button(btns, text='Copy Selected', command=lambda: self.run_action('Copy Selected Row', self._copy_archive_row)).pack(side='middle', padx=(8, 0))
        ttk.Button(btns, text='Copy all as TSV', command=lambda: self.run_action('Copy All Rows', self._copy_all_archive_rows)).pack(side='middle', padx=(8, 0))

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
        self.archive_tree.grid(row=3, column=0, columnspan=2, sticky='nsew')
        yscroll.grid(row=3, column=2, sticky='ns')
        xscroll.grid(row=4, column=0, columnspan=2, sticky='ew')

        self.archive_summary = tk.Text(tab, height=8, wrap='word')
        self.archive_summary.grid(row=5, column=0, columnspan=3, sticky='ew', pady=(8, 0))
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

    def _get_selected_archive_table_index(self) -> int:
        selected = self.archive_tree.selection()
        if not selected:
            raise ToolError('Select a row in the CombinedAudio Table tab first.')
        values = self.archive_tree.item(selected[0], 'values')
        if not values:
            raise ToolError('Could not read the selected CombinedAudio row.')
        return int(values[0])

    def _cleanup_preview_temp(self):
        temp_path = getattr(self, '_preview_temp_wav', None)
        self._preview_temp_wav = None
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass

    def _play_wav_bytes(self, wav_bytes: bytes):
        if winsound is None:
            raise ToolError('Playback is only available on Windows via winsound.')
        if not wav_bytes:
            raise ToolError('No WAV data was generated for playback.')
        self._stop_playback(silent=True)
        self._current_wav_bytes = wav_bytes
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        try:
            tmp.write(wav_bytes)
            tmp.flush()
        finally:
            tmp.close()
        self._preview_temp_wav = tmp.name
        winsound.PlaySound(self._preview_temp_wav, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    def _stop_playback(self, silent: bool = False):
        if winsound is None:
            raise ToolError('Playback stop is only available on Windows via winsound.')
        winsound.PlaySound(None, 0)
        self._current_wav_bytes = None
        self._cleanup_preview_temp()
        if not silent:
            return 'Stopped audio playback.'

    def _play_archive_selection(self):
        combined_audio_path = Path(self.archive_path.get())
        table_index = self._get_selected_archive_table_index()
        wav_bytes = self.backend.get_combined_audio_entry_wav_bytes(combined_audio_path, table_index)
        self._play_wav_bytes(wav_bytes)
        return f'Playing CombinedAudio table entry #{table_index} from memory.'

    def _reload_archive_table(self):
        return self._load_archive_table()

    def _replace_archive_selection(self):
        combined_audio_path = Path(self.archive_path.get())
        table_index = self._get_selected_archive_table_index()
        replacement = filedialog.askopenfilename(filetypes=(("Supported Audio/FSB", "*.fsb *.wav *.wave *.dsp"), ("All Files", "*.*")))
        if not replacement:
            return 'Replacement canceled.'
        output_text = self.archive_out_path.get().strip()
        output_path = Path(output_text) if output_text else combined_audio_path
        result = self.backend.replace_combined_audio_entry_from_file(combined_audio_path, table_index, Path(replacement), output_path=output_path)
        self.archive_path.set(str(result))
        self._load_archive_table()
        return f'Replaced CombinedAudio table entry #{table_index} using {Path(replacement).name} and reloaded: {result}'

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

try:
    import tkinterdnd2 as _tkdnd2
except Exception:
    _tkdnd2 = None

def _ca_chunk_header(chunk_type: int, size: int, next_flag: int) -> bytes:
    raw = (next_flag & 0x1) | ((size & 0xFFFFFF) << 1) | ((chunk_type & 0x7F) << 25)
    return struct.pack('<I', raw)


def _ca_seconds_to_samples(seconds: float, sample_rate: int) -> int:
    return max(0, int(round(float(seconds) * float(sample_rate))))


def _backend_inspect_wav_bytes(self, wav_bytes: bytes):
    if not wav_bytes:
        raise ToolError('No WAV data was provided.')
    with wave.open(io.BytesIO(wav_bytes), 'rb') as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frame_count = wf.getnframes()
        raw = wf.readframes(frame_count)
    duration = (frame_count / sample_rate) if sample_rate else 0.0
    pcm = np.frombuffer(raw, dtype='<i2') if sample_width == 2 else np.frombuffer(raw, dtype=np.uint8)
    if sample_width == 2 and channels > 1:
        pcm = pcm.reshape(-1, channels)
    peak = 0.0
    if sample_width == 2 and pcm.size:
        peak = float(np.max(np.abs(pcm.astype(np.int32)))) / 32767.0
    return {
        'kind': 'wav',
        'channels': channels,
        'sample_width': sample_width,
        'sample_rate': sample_rate,
        'sample_count': frame_count,
        'duration': duration,
        'pcm': pcm,
        'peak': peak,
    }


def _backend_inspect_fsb_bytes_detailed(self, fsb_bytes: bytes):
    info = self._extract_fsb_sample_metadata(fsb_bytes)
    mode_names = {1: 'PCM8', 2: 'PCM16', 6: 'GCADPCM', 16: 'FADPCM'}
    loop_start = None
    loop_end = None
    embedded_name = self.get_segment_name_bytes(fsb_bytes)
    for chunk in self._iter_sample_chunks(info['meta']['sample_header']):
        if chunk['type'] == 3 and chunk['size'] == 8:
            loop_start, loop_end = struct.unpack_from('<II', info['meta']['sample_header'], chunk['data_offset'])
            break
    duration = (info['sample_count'] / info['sample_rate']) if info['sample_rate'] else 0.0
    return {
        'kind': 'fsb',
        'mode': info['mode'],
        'mode_name': mode_names.get(info['mode'], f'Mode {info["mode"]}'),
        'channels': info['channels'],
        'sample_rate': info['sample_rate'],
        'sample_count': info['sample_count'],
        'duration': duration,
        'data_size': len(info['payload']),
        'loop_start': loop_start,
        'loop_end': loop_end,
        'embedded_name': embedded_name or '',
    }


def _backend_inspect_dsp_bytes_detailed(self, dsp_bytes: bytes):
    if len(dsp_bytes) < DSP_HEADER_SIZE:
        raise ToolError('DSP data is smaller than the required 0x60-byte header.')
    h = self.read_dsp_header_bytes(dsp_bytes) if hasattr(self, 'read_dsp_header_bytes') else None
    if h is None:
        h1 = self._parse_single_dsp_header(dsp_bytes[:DSP_HEADER_SIZE])
        channels = 1
        coeff_blob = h1['coeff_blob']
        raw_header = h1['raw_header']
        data_offset = DSP_HEADER_SIZE
        if len(dsp_bytes) >= DSP_HEADER_SIZE * 2:
            try:
                h2 = self._parse_single_dsp_header(dsp_bytes[DSP_HEADER_SIZE:DSP_HEADER_SIZE * 2])
            except ToolError:
                h2 = None
            if h2 and all(h1[k] == h2[k] for k in ('sample_count', 'nibble_count', 'sample_rate', 'loop_flag', 'fmt')):
                channels = 2
                coeff_blob = h1['coeff_blob'] + h2['coeff_blob']
                raw_header = dsp_bytes[:DSP_HEADER_SIZE * 2]
                data_offset = DSP_HEADER_SIZE * 2
        h = DspHeader(
            sample_count=h1['sample_count'], nibble_count=h1['nibble_count'], sample_rate=h1['sample_rate'],
            loop_flag=h1['loop_flag'], fmt=h1['fmt'], loop_start=h1['loop_start'], loop_end=h1['loop_end'],
            current_address=h1['current_address'], channels=channels, block_size=h1['block_size'], coeff_blob=coeff_blob,
            raw_header=raw_header, data_offset=data_offset,
        )
    duration = (h.sample_count / h.sample_rate) if h.sample_rate else 0.0
    loop_start_samples = max(0, ((h.loop_start - 2) // 16) * 14 + ((h.loop_start - 2) % 16)) if h.loop_flag else None
    loop_end_samples = max(0, ((h.loop_end - 2) // 16) * 14 + ((h.loop_end - 2) % 16) + 1) if h.loop_flag else None
    return {
        'kind': 'dsp',
        'mode': 6,
        'mode_name': 'GCADPCM (DSP)',
        'channels': h.channels,
        'sample_rate': h.sample_rate,
        'sample_count': h.sample_count,
        'duration': duration,
        'data_size': max(0, len(dsp_bytes) - h.data_offset),
        'loop_start': loop_start_samples,
        'loop_end': loop_end_samples,
    }


def _backend_inspect_audio_path(self, path: Path):
    self.ensure_exists(path)
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix in ('.wav', '.wave'):
        return self.inspect_wav_bytes(data)
    if suffix == '.dsp':
        return self.inspect_dsp_bytes_detailed(data)
    if suffix == '.fsb' or data[:4] == b'FSB5':
        return self.inspect_fsb_bytes_detailed(data)
    raise ToolError(f'Unsupported audio path for inspection: {path}')


def _backend_read_dsp_header_bytes(self, dsp_bytes: bytes):
    if len(dsp_bytes) < DSP_HEADER_SIZE:
        raise ToolError('DSP file is smaller than 0x60-byte header.')
    h1 = self._parse_single_dsp_header(dsp_bytes[:DSP_HEADER_SIZE])
    channels = 1
    coeff_blob = h1['coeff_blob']
    raw_header = h1['raw_header']
    data_offset = DSP_HEADER_SIZE
    if len(dsp_bytes) >= DSP_HEADER_SIZE * 2:
        try:
            h2 = self._parse_single_dsp_header(dsp_bytes[DSP_HEADER_SIZE:DSP_HEADER_SIZE * 2])
        except ToolError:
            h2 = None
        if h2 and all(h1[k] == h2[k] for k in ('sample_count', 'nibble_count', 'sample_rate', 'loop_flag', 'fmt')):
            channels = 2
            coeff_blob = h1['coeff_blob'] + h2['coeff_blob']
            raw_header = dsp_bytes[:DSP_HEADER_SIZE * 2]
            data_offset = DSP_HEADER_SIZE * 2
    return DspHeader(
        sample_count=h1['sample_count'], nibble_count=h1['nibble_count'], sample_rate=h1['sample_rate'],
        loop_flag=h1['loop_flag'], fmt=h1['fmt'], loop_start=h1['loop_start'], loop_end=h1['loop_end'],
        current_address=h1['current_address'], channels=channels, block_size=h1['block_size'], coeff_blob=coeff_blob,
        raw_header=raw_header, data_offset=data_offset,
    )


def _backend_build_mode2_fsb_from_wav(self, wav_path: Path, out_path: Path, embedded_name: str = ''):
    self.ensure_exists(wav_path)
    sample_rate, channels, samples = self._load_wav_pcm16(wav_path)
    pcm_bytes = samples.astype('<i2').tobytes()
    sample_count = len(samples)
    sample_mode = ((sample_count & 0x3FFFFFFF) << 34) | 0x1
    sample_header = bytearray(struct.pack('<Q', sample_mode))
    sample_header += _ca_chunk_header(1, 1, 1) + bytes([channels & 0xFF])
    sample_header += _ca_chunk_header(2, 4, 0) + struct.pack('<I', sample_rate)
    name_table = b''
    if embedded_name:
        safe_name = embedded_name.encode('ascii', errors='ignore')[:255]
        name_table = safe_name + b'\x00'
    version = 0
    num_samples = 1
    sample_header_size = len(sample_header)
    name_table_size = len(name_table)
    data_size = len(pcm_bytes)
    mode = 2
    header_size = 64
    header = bytearray(header_size)
    header[:4] = b'FSB5'
    struct.pack_into('<IIIIII', header, 4, version, num_samples, sample_header_size, name_table_size, data_size, mode)
    out = bytes(header) + bytes(sample_header) + name_table + pcm_bytes
    Path(out_path).write_bytes(out)
    return Path(out_path)


def _backend_patch_fsb_loop_bytes(self, fsb_bytes: bytes, loop_start_samples: int, loop_end_samples: int):
    blob = bytearray(fsb_bytes)
    meta = self._parse_fsb_header(blob)
    sh = bytearray(meta['sample_header'])
    found = False
    last_chunk = None
    for chunk in self._iter_sample_chunks(sh):
        last_chunk = chunk
        if chunk['type'] == 3 and chunk['size'] == 8:
            struct.pack_into('<II', sh, chunk['data_offset'], int(loop_start_samples), int(loop_end_samples))
            found = True
            break
    if not found:
        if last_chunk is not None:
            raw = struct.unpack_from('<I', sh, last_chunk['header_offset'])[0]
            raw |= 0x1
            struct.pack_into('<I', sh, last_chunk['header_offset'], raw)
        elif sh:
            sh[0] |= 0x1
        sh += _ca_chunk_header(3, 8, 0) + struct.pack('<II', int(loop_start_samples), int(loop_end_samples))
        prefix = blob[:meta['sample_header_off']]
        suffix = blob[meta['name_table_off']:]
        blob = bytearray(prefix + sh + suffix)
        struct.pack_into('<I', blob, 12, len(sh))
    else:
        blob[meta['sample_header_off']:meta['sample_header_off'] + meta['sample_header_size']] = sh
    return bytes(blob)


def _backend_try_patch_embedded_name(self, fsb_bytes: bytes, new_name: str):
    old_name = self.get_segment_name_bytes(fsb_bytes)
    if not old_name:
        raise ToolError('No embedded segment name was found in this FSB segment.')
    old_bytes = old_name.encode('ascii', errors='ignore')
    new_bytes = new_name.encode('ascii', errors='ignore')
    if not new_bytes:
        raise ToolError('Embedded segment name cannot be empty.')
    if len(new_bytes) > len(old_bytes):
        raise ToolError(f'New embedded segment name is longer than the existing field ({len(new_bytes)} > {len(old_bytes)}). Shorten it or keep the same length.')
    blob = bytearray(fsb_bytes)
    idx = bytes(blob).rfind(old_bytes)
    if idx < 0:
        raise ToolError('Could not locate the embedded segment name inside the FSB blob.')
    padded = new_bytes + (b'\x00' * (len(old_bytes) - len(new_bytes)))
    blob[idx:idx + len(old_bytes)] = padded
    return bytes(blob)


def _backend_update_combinedaudio_entry(self, combined_audio_path: Path, table_index: int, new_blob: bytes = None, new_sound_id: int = None, output_path: Path = None):
    parsed = self.parse_combined_audio_table(combined_audio_path)
    if table_index < 0 or table_index >= len(parsed['entries']):
        raise ToolError(f'CombinedAudio table index out of range: {table_index}')
    output_path = Path(output_path or combined_audio_path)
    physical_entries = list(parsed['entries_by_physical'])
    replacement_map = {entry.table_index: parsed['data'][entry.absolute_offset:entry.absolute_end_offset] for entry in parsed['entries']}
    sound_id_map = {entry.table_index: entry.sound_id for entry in parsed['entries']}
    if new_blob is not None:
        if not bytes(new_blob).startswith(b'FSB5'):
            raise ToolError('Updated entry blob must be an FSB5 segment.')
        replacement_map[table_index] = bytes(new_blob)
    if new_sound_id is not None:
        sound_id_map[table_index] = int(new_sound_id)
    entries = [None] * parsed['entry_count']
    data_chunks = []
    current_offset = 0
    for entry in physical_entries:
        blob = replacement_map[entry.table_index]
        current_offset = self._align_up(current_offset)
        entries[entry.table_index] = (sound_id_map[entry.table_index], current_offset, len(blob))
        data_chunks.append((current_offset, blob))
        current_offset += len(blob)
    header = bytearray(4 + (parsed['entry_count'] * 12))
    struct.pack_into('<I', header, 0, parsed['entry_count'])
    for idx, packed in enumerate(entries):
        sound_id, fsb_offset, fsb_size = packed
        struct.pack_into('<III', header, 4 + (idx * 12), sound_id, fsb_offset, fsb_size)
    out = bytearray(header)
    header_length = len(header)
    for fsb_offset, blob in data_chunks:
        absolute_offset = header_length + fsb_offset
        if len(out) < absolute_offset:
            out.extend(b'\x00' * (absolute_offset - len(out)))
        out.extend(blob)
    output_path.write_bytes(bytes(out))
    return output_path


CAToolBackend.inspect_wav_bytes = _backend_inspect_wav_bytes
CAToolBackend.inspect_fsb_bytes_detailed = _backend_inspect_fsb_bytes_detailed
CAToolBackend.inspect_dsp_bytes_detailed = _backend_inspect_dsp_bytes_detailed
CAToolBackend.inspect_audio_path = _backend_inspect_audio_path
CAToolBackend.read_dsp_header_bytes = _backend_read_dsp_header_bytes
CAToolBackend.build_mode2_fsb_from_wav = _backend_build_mode2_fsb_from_wav
CAToolBackend.patch_fsb_loop_bytes = _backend_patch_fsb_loop_bytes
CAToolBackend.try_patch_embedded_name = _backend_try_patch_embedded_name
CAToolBackend.update_combinedaudio_entry = _backend_update_combinedaudio_entry


def _gui_init_archive_state(self):
    self._archive_preview_cache = {}
    self._playback_after_id = None
    self._loop_after_id = None
    self._preview_temp_wav = None
    self._current_wav_bytes = None
    self._current_preview_meta = None
    self._sidecar_cache = None


def _gui_sidecar_path(self):
    p = Path(self.archive_path.get().strip())
    return p.with_suffix(p.suffix + '.sidecar.json') if p.suffix else p.with_name(p.name + '.sidecar.json')


def _gui_load_sidecar(self):
    sidecar = self._gui_sidecar_path()
    if sidecar.exists():
        try:
            self._sidecar_cache = json.loads(sidecar.read_text(encoding='utf-8'))
        except Exception:
            self._sidecar_cache = {'entries': {}}
    else:
        self._sidecar_cache = {'entries': {}}
    self._sidecar_cache.setdefault('entries', {})
    return self._sidecar_cache


def _gui_save_sidecar(self):
    if self._sidecar_cache is None:
        self._gui_load_sidecar()
    sidecar = self._gui_sidecar_path()
    sidecar.write_text(json.dumps(self._sidecar_cache, indent=2), encoding='utf-8')
    return sidecar


def _gui_build_archive_tab(self, tab):
    self._gui_init_archive_state()
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(3, weight=1)
    self.archive_path = tk.StringVar()
    self.archive_out_path = tk.StringVar()
    self.archive_seek_var = tk.DoubleVar(value=0.0)
    self.archive_seek_label_var = tk.StringVar(value='Seek: 0.000s')
    self.archive_autoplay_next_var = tk.BooleanVar(value=False)
    self.archive_loop_preview_var = tk.BooleanVar(value=False)
    self.loop_start_samples_var = tk.StringVar(value='0')
    self.loop_end_samples_var = tk.StringVar(value='0')
    self.loop_start_seconds_var = tk.StringVar(value='0.000')
    self.loop_end_seconds_var = tk.StringVar(value='0.000')
    self.meta_sound_id_var = tk.StringVar()
    self.meta_embedded_name_var = tk.StringVar()
    self.meta_alias_var = tk.StringVar()
    self.meta_notes_var = tk.StringVar()
    self.convert_template_fsb = tk.StringVar()
    self.convert_mode_wav_in = tk.StringVar()
    self.convert_mode2_out = tk.StringVar()
    self.convert_mode6_out = tk.StringVar()

    self.add_path_row(tab, 0, 'CombinedAudio.bin', self.archive_path, filetypes=(("BIN Files", "*.bin"), ("All Files", "*.*")))
    self.add_path_row(tab, 1, 'Replacement output (.bin, optional)', self.archive_out_path, filetypes=(("BIN Files", "*.bin"),), save=True, default_ext='.bin')

    btns = ttk.Frame(tab)
    btns.grid(row=2, column=0, columnspan=3, sticky='w', pady=(4, 8))
    for text, cmd in [
        ('Load CombinedAudio', lambda: self.run_action('CombinedAudio Table', self._load_archive_table)),
        ('Replace Selected SFX', lambda: self.run_action('Replace Selected Sound', self._replace_archive_selection)),
        ('Apply Loop Edit', lambda: self.run_action('Apply Loop Edit', self._apply_loop_metadata_to_selected)),
        ('Save Metadata', lambda: self.run_action('Save Entry Metadata', self._save_selected_metadata)),
        ('Reload Table', lambda: self.run_action('Reload Table', self._reload_archive_table)),
        ('Copy Selected', lambda: self.run_action('Copy Selected Row', self._copy_archive_row)),
        ('Copy all as TSV', lambda: self.run_action('Copy All Rows', self._copy_all_archive_rows)),
    ]:
        ttk.Button(btns, text=text, command=cmd).pack(side='left', padx=(0, 6))

    content = ttk.Panedwindow(tab, orient='horizontal')
    content.grid(row=3, column=0, columnspan=3, sticky='nsew')

    tree_panel = ttk.Frame(content, padding=4)
    preview_panel = ttk.Frame(content, padding=4)
    right_panel = ttk.Frame(content, padding=4)
    content.add(tree_panel, weight=4)
    content.add(preview_panel, weight=4)
    content.add(right_panel, weight=3)

    tree_panel.columnconfigure(0, weight=1)
    tree_panel.rowconfigure(1, weight=1)
    ttk.Label(tree_panel, text='CombinedAudio Entries').grid(row=0, column=0, columnspan=2, sticky='w')

    columns = ('table_index', 'physical_index', 'sound_id', 'offset_hex', 'size', 'end_hex', 'fsb_name', 'alias')
    self.archive_tree = ttk.Treeview(tree_panel, columns=columns, show='headings', height=18)
    headings = {
        'table_index': 'Table #', 'physical_index': 'Segment #', 'sound_id': 'Sound ID', 'offset_hex': 'Offset',
        'size': 'Size', 'end_hex': 'End', 'fsb_name': 'FSB Name', 'alias': 'Alias',
    }
    widths = {'table_index': 70, 'physical_index': 80, 'sound_id': 100, 'offset_hex': 95, 'size': 75, 'end_hex': 95, 'fsb_name': 200, 'alias': 140}
    for col in columns:
        self.archive_tree.heading(col, text=headings[col])
        self.archive_tree.column(col, width=widths[col], anchor='w', stretch=(col in ('fsb_name', 'alias')))
    self.archive_tree.grid(row=1, column=0, sticky='nsew')
    tree_yscroll = ttk.Scrollbar(tree_panel, orient='vertical', command=self.archive_tree.yview)
    tree_yscroll.grid(row=1, column=1, sticky='ns')
    tree_xscroll = ttk.Scrollbar(tree_panel, orient='horizontal', command=self.archive_tree.xview)
    tree_xscroll.grid(row=2, column=0, sticky='ew', pady=(2, 0))
    self.archive_tree.configure(yscrollcommand=tree_yscroll.set, xscrollcommand=tree_xscroll.set)
    self.archive_tree.bind('<<TreeviewSelect>>', lambda e: self._on_archive_tree_select())

    preview_panel.columnconfigure(0, weight=1)
    preview_panel.rowconfigure(6, weight=1)
    ttk.Label(preview_panel, text='Waveform Preview').grid(row=0, column=0, sticky='w')
    self.waveform_canvas = tk.Canvas(preview_panel, width=640, height=210, bg='#101010', highlightthickness=1, highlightbackground='#404040')
    self.waveform_canvas.grid(row=1, column=0, sticky='ew', pady=(4, 6))

    preview_btns = ttk.Frame(preview_panel)
    preview_btns.grid(row=2, column=0, sticky='w', pady=(0, 6))
    for text, cmd in [
        ('Play Selected FSB', lambda: self.run_action('Play Selected FSB', self._play_archive_selection)),
        ('Play via seek', lambda: self.run_action('Play From Seek', self._play_from_seek)),
        ('Restart', lambda: self.run_action('Restart Playback', self._restart_preview_playback)),
        ('Next', lambda: self.run_action('Next Entry', self._play_next_archive_entry)),
        ('Stop Playback', lambda: self.run_action('Stop Playback', self._stop_playback)),
    ]:
        ttk.Button(preview_btns, text=text, command=cmd).pack(side='left', padx=(0, 6))

    seek_row = ttk.Frame(preview_panel)
    seek_row.grid(row=3, column=0, sticky='ew')
    ttk.Label(seek_row, textvariable=self.archive_seek_label_var).pack(side='left')
    ttk.Checkbutton(seek_row, text='Autoplay next', variable=self.archive_autoplay_next_var).pack(side='right')
    ttk.Checkbutton(seek_row, text='Loop preview', variable=self.archive_loop_preview_var).pack(side='right', padx=(0, 12))
    self.archive_seek_scale = tk.Scale(preview_panel, from_=0.0, to=1.0, resolution=0.001, orient='horizontal', variable=self.archive_seek_var, showvalue=False, command=lambda _v: self._update_seek_label())
    self.archive_seek_scale.grid(row=4, column=0, sticky='ew')
    ttk.Label(preview_panel, text='Entry Summary / Preview Log').grid(row=5, column=0, sticky='w', pady=(8, 4))
    self.archive_summary = tk.Text(preview_panel, height=16, wrap='word')
    self.archive_summary.grid(row=6, column=0, sticky='nsew')
    preview_scroll = ttk.Scrollbar(preview_panel, orient='vertical', command=self.archive_summary.yview)
    preview_scroll.grid(row=6, column=1, sticky='ns')
    self.archive_summary.configure(state='disabled', yscrollcommand=preview_scroll.set)

    right_panel.columnconfigure(1, weight=1)
    ttk.Label(right_panel, text='Loop / Metadata Editor').grid(row=0, column=0, columnspan=2, sticky='w')
    fields = [
        ('Loop Start (samples)', self.loop_start_samples_var),
        ('Loop End (samples)', self.loop_end_samples_var),
        ('Loop Start (seconds)', self.loop_start_seconds_var),
        ('Loop End (seconds)', self.loop_end_seconds_var),
        ('Sound ID', self.meta_sound_id_var),
        ('Embedded name', self.meta_embedded_name_var),
        ('Alias', self.meta_alias_var),
        ('Notes / comments', self.meta_notes_var),
    ]
    for idx, (label, var) in enumerate(fields, start=1):
        ttk.Label(right_panel, text=label).grid(row=idx, column=0, sticky='w', pady=2)
        ttk.Entry(right_panel, textvariable=var).grid(row=idx, column=1, sticky='ew', pady=2)

    ttk.Separator(right_panel, orient='horizontal').grid(row=10, column=0, columnspan=2, sticky='ew', pady=8)
    ttk.Label(right_panel, text='Mode conversion').grid(row=11, column=0, columnspan=2, sticky='w')
    ttk.Label(right_panel, text='Template FSB (for Mode 6)').grid(row=12, column=0, sticky='w', pady=2)
    ttk.Entry(right_panel, textvariable=self.convert_template_fsb).grid(row=12, column=1, sticky='ew', pady=2)
    ttk.Label(right_panel, text='Source WAV').grid(row=13, column=0, sticky='w', pady=2)
    ttk.Entry(right_panel, textvariable=self.convert_mode_wav_in).grid(row=13, column=1, sticky='ew', pady=2)
    ttk.Label(right_panel, text='Mode 2 FSB output').grid(row=14, column=0, sticky='w', pady=2)
    ttk.Entry(right_panel, textvariable=self.convert_mode2_out).grid(row=14, column=1, sticky='ew', pady=2)
    ttk.Label(right_panel, text='Mode 6 FSB output').grid(row=15, column=0, sticky='w', pady=2)
    ttk.Entry(right_panel, textvariable=self.convert_mode6_out).grid(row=15, column=1, sticky='ew', pady=2)
    conv_btns = ttk.Frame(right_panel)
    conv_btns.grid(row=16, column=0, columnspan=2, sticky='w', pady=(6, 0))
    ttk.Button(conv_btns, text='WAV → Mode 2 FSB', command=lambda: self.run_action('WAV → Mode 2 FSB', self._convert_wav_to_mode2_fsb)).pack(side='left')
    ttk.Button(conv_btns, text='WAV → Mode 6 FSB', command=lambda: self.run_action('WAV → Mode 6 FSB', self._convert_wav_to_mode6_fsb)).pack(side='left', padx=(6, 0))

    if _tkdnd2 is not None:
        try:
            self.archive_tree.drop_target_register(_tkdnd2.DND_FILES)
            self.archive_tree.dnd_bind('<<Drop>>', lambda event: self._on_archive_drop(event))
        except Exception:
            pass


def _gui_draw_waveform(self, wav_bytes: bytes):
    self.waveform_canvas.delete('all')
    info = self.backend.inspect_wav_bytes(wav_bytes)
    pcm = info['pcm']
    if info['sample_width'] != 2 or pcm.size == 0:
        self.waveform_canvas.create_text(10, 10, anchor='nw', fill='white', text='Waveform preview requires 16-bit decoded WAV data.')
        return info
    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1)
    width = max(1, int(self.waveform_canvas.winfo_width() or 640))
    height = max(1, int(self.waveform_canvas.winfo_height() or 180))
    self.waveform_canvas.create_rectangle(0, 0, width, height, outline='')
    center_y = height / 2.0
    samples = pcm.astype(np.float32)
    step = max(1, len(samples) // width)
    peaks = []
    for x in range(width):
        chunk = samples[x * step:(x + 1) * step]
        if chunk.size == 0:
            amp = 0.0
        else:
            amp = float(np.max(np.abs(chunk))) / 32767.0
        peaks.append(amp)
    for x, amp in enumerate(peaks):
        y = amp * (height * 0.45)
        self.waveform_canvas.create_line(x, center_y - y, x, center_y + y, fill='#4ec9b0')
    self.waveform_canvas.create_line(0, center_y, width, center_y, fill='#404040')
    return info


def _gui_trim_wav_bytes(self, wav_bytes: bytes, start_seconds: float = 0.0, end_seconds: float = None):
    with wave.open(io.BytesIO(wav_bytes), 'rb') as src:
        channels = src.getnchannels()
        sampwidth = src.getsampwidth()
        framerate = src.getframerate()
        frame_count = src.getnframes()
        raw = src.readframes(frame_count)
    if sampwidth not in (1, 2, 3, 4):
        raise ToolError('Unsupported WAV sample width for trimming.')
    start_frame = max(0, min(frame_count, int(round(start_seconds * framerate))))
    end_frame = frame_count if end_seconds is None else max(start_frame, min(frame_count, int(round(end_seconds * framerate))))
    bytes_per_frame = channels * sampwidth
    body = raw[start_frame * bytes_per_frame:end_frame * bytes_per_frame]
    out = io.BytesIO()
    with wave.open(out, 'wb') as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(sampwidth)
        dst.setframerate(framerate)
        dst.writeframes(body)
    return out.getvalue(), (end_frame - start_frame) / framerate if framerate else 0.0


def _gui_cancel_playback_after(self):
    for attr in ('_playback_after_id', '_loop_after_id'):
        handle = getattr(self, attr, None)
        if handle:
            try:
                self.after_cancel(handle)
            except Exception:
                pass
            setattr(self, attr, None)


def _gui_update_seek_label(self):
    seconds = float(self.archive_seek_var.get())
    self.archive_seek_label_var.set(f'Seek: {seconds:.3f}s')


def _gui_set_archive_summary(self, text: str):
    self.archive_summary.configure(state='normal')
    self.archive_summary.delete('1.0', 'end')
    self.archive_summary.insert('1.0', text)
    self.archive_summary.configure(state='disabled')


def _gui_get_selected_archive_table_index(self) -> int:
    selected = self.archive_tree.selection()
    if not selected:
        raise ToolError('Select a row in the CombinedAudio Table tab first.')
    values = self.archive_tree.item(selected[0], 'values')
    if not values:
        raise ToolError('Could not read the selected CombinedAudio row.')
    return int(values[0])


def _gui_load_archive_table(self):
    info = self.backend.inspect_combined_audio(Path(self.archive_path.get()))
    sidecar = self._gui_load_sidecar()
    for item in self.archive_tree.get_children():
        self.archive_tree.delete(item)
    for row in sorted(info['rows'], key=lambda r: r['table_index']):
        extra = sidecar['entries'].get(str(row['table_index']), {})
        self.archive_tree.insert('', 'end', values=(row['table_index'], row['physical_index'], row['sound_id'], f"0x{row['offset']:X}", row['size'], f"0x{row['end_offset']:X}", row['fsb_name'], extra.get('alias', '')))
    summary = (
        f"Entry count: {info['entry_count']}\n"
        f"Header length: 0x{info['header_length']:X} ({info['header_length']})\n"
        f"File size: 0x{info['file_size']:X} ({info['file_size']})\n"
        f"Rows loaded: {len(info['rows'])}\n"
        "Columns: table index, physical FSB order, sound ID, offset, size, end offset, embedded FSB name, alias."
    )
    self._gui_set_archive_summary(summary)
    if info['rows']:
        first = self.archive_tree.get_children()[0]
        self.archive_tree.selection_set(first)
        self.archive_tree.focus(first)
        self._on_archive_tree_select()
    return f'Loaded {len(info["rows"])} CombinedAudio entries.'


def _gui_prepare_preview_for_table_index(self, table_index: int):
    key = ('table', str(Path(self.archive_path.get())), table_index)
    cached = self._archive_preview_cache.get(key)
    if cached:
        return cached
    fsb_bytes = self.backend.get_combined_audio_entry_fsb_bytes(Path(self.archive_path.get()), table_index)
    wav_bytes = self.backend.decode_fsb_bytes_to_wav_bytes(fsb_bytes)
    fsb_info = self.backend.inspect_fsb_bytes_detailed(fsb_bytes)
    wav_info = self.backend.inspect_wav_bytes(wav_bytes)
    data = {'fsb_bytes': fsb_bytes, 'wav_bytes': wav_bytes, 'fsb_info': fsb_info, 'wav_info': wav_info}
    self._archive_preview_cache[key] = data
    return data


def _gui_on_archive_tree_select(self):
    try:
        table_index = self._gui_get_selected_archive_table_index()
    except Exception:
        return
    data = self._gui_prepare_preview_for_table_index(table_index)
    wav_info = self._gui_draw_waveform(data['wav_bytes'])
    fsb_info = data['fsb_info']
    self._current_preview_meta = data
    self.archive_seek_scale.configure(to=max(0.001, wav_info['duration']))
    self.archive_seek_var.set(0.0)
    self._gui_update_seek_label()
    self.loop_start_samples_var.set(str(fsb_info.get('loop_start') or 0))
    self.loop_end_samples_var.set(str(fsb_info.get('loop_end') or fsb_info['sample_count']))
    if fsb_info.get('loop_start') is not None:
        self.loop_start_seconds_var.set(f"{fsb_info['loop_start'] / fsb_info['sample_rate']:.3f}")
    else:
        self.loop_start_seconds_var.set('0.000')
    if fsb_info.get('loop_end') is not None:
        self.loop_end_seconds_var.set(f"{fsb_info['loop_end'] / fsb_info['sample_rate']:.3f}")
    else:
        self.loop_end_seconds_var.set(f"{fsb_info['duration']:.3f}")
    self.meta_sound_id_var.set(str(self.archive_tree.item(self.archive_tree.selection()[0], 'values')[2]))
    self.meta_embedded_name_var.set(fsb_info.get('embedded_name', ''))
    side = self._gui_load_sidecar()['entries'].get(str(table_index), {})
    self.meta_alias_var.set(side.get('alias', ''))
    self.meta_notes_var.set(side.get('notes', ''))
    summary = [
        f"Table entry: {table_index}",
        f"Mode: {fsb_info['mode_name']} ({fsb_info['mode']})",
        f"Sample rate: {fsb_info['sample_rate']} Hz",
        f"Channels: {fsb_info['channels']}",
        f"Samples: {fsb_info['sample_count']}",
        f"Duration: {fsb_info['duration']:.3f}s",
        f"Payload/data size: {fsb_info['data_size']} bytes",
        f"Loop: {fsb_info.get('loop_start')} -> {fsb_info.get('loop_end')}",
        f"Embedded name: {fsb_info.get('embedded_name', '') or '(none)'}",
        f"Alias: {side.get('alias', '') or '(none)'}",
        f"Notes: {side.get('notes', '') or '(none)'}",
    ]
    self._gui_set_archive_summary('\n'.join(summary))


def _gui_cleanup_preview_temp(self):
    temp_path = getattr(self, '_preview_temp_wav', None)
    self._preview_temp_wav = None
    if temp_path:
        try:
            Path(temp_path).unlink(missing_ok=True)
        except Exception:
            pass


def _gui_play_wav_bytes(self, wav_bytes: bytes, playback_duration: float = None, restart_callback=None):
    if winsound is None:
        raise ToolError('Playback is only available on Windows via winsound.')
    if not wav_bytes:
        raise ToolError('No WAV data was generated for playback.')
    self._stop_playback(silent=True)
    self._current_wav_bytes = wav_bytes
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    try:
        tmp.write(wav_bytes)
        tmp.flush()
    finally:
        tmp.close()
    self._preview_temp_wav = tmp.name
    winsound.PlaySound(self._preview_temp_wav, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    self._gui_cancel_playback_after()
    if playback_duration is not None and playback_duration > 0:
        if restart_callback is not None:
            self._loop_after_id = self.after(max(1, int(playback_duration * 1000)), restart_callback)
        elif self.archive_autoplay_next_var.get():
            self._playback_after_id = self.after(max(1, int(playback_duration * 1000)), lambda: self.run_action('Autoplay Next', self._play_next_archive_entry))


def _gui_stop_playback(self, silent: bool = False):
    if winsound is None:
        raise ToolError('Playback stop is only available on Windows via winsound.')
    winsound.PlaySound(None, 0)
    self._current_wav_bytes = None
    self._gui_cancel_playback_after()
    self._gui_cleanup_preview_temp()
    if not silent:
        return 'Stopped audio playback.'


def _gui_play_archive_selection(self):
    table_index = self._gui_get_selected_archive_table_index()
    data = self._gui_prepare_preview_for_table_index(table_index)
    if self.archive_loop_preview_var.get() and data['fsb_info'].get('loop_start') is not None and data['fsb_info'].get('loop_end') is not None:
        sr = data['fsb_info']['sample_rate']
        start_s = data['fsb_info']['loop_start'] / sr
        end_s = data['fsb_info']['loop_end'] / sr
        loop_wav, dur = self._gui_trim_wav_bytes(data['wav_bytes'], start_s, end_s)
        self._gui_play_wav_bytes(loop_wav, dur, restart_callback=lambda: self._gui_play_wav_bytes(loop_wav, dur, restart_callback=lambda: self._gui_play_wav_bytes(loop_wav, dur, restart_callback=lambda: self._play_archive_selection())))
        return f'Loop-previewing CombinedAudio table entry #{table_index}.'
    self._gui_play_wav_bytes(data['wav_bytes'], data['wav_info']['duration'])
    return f'Playing CombinedAudio table entry #{table_index} from memory.'


def _gui_play_from_seek(self):
    table_index = self._gui_get_selected_archive_table_index()
    data = self._gui_prepare_preview_for_table_index(table_index)
    start = float(self.archive_seek_var.get())
    if self.archive_loop_preview_var.get() and data['fsb_info'].get('loop_start') is not None and data['fsb_info'].get('loop_end') is not None:
        start = max(start, data['fsb_info']['loop_start'] / data['fsb_info']['sample_rate'])
        end = data['fsb_info']['loop_end'] / data['fsb_info']['sample_rate']
        trim, dur = self._gui_trim_wav_bytes(data['wav_bytes'], start, end)
        self._gui_play_wav_bytes(trim, dur)
        return f'Playing loop preview of entry #{table_index} from {start:.3f}s.'
    trim, dur = self._gui_trim_wav_bytes(data['wav_bytes'], start, None)
    self._gui_play_wav_bytes(trim, dur)
    return f'Playing entry #{table_index} from {start:.3f}s.'


def _gui_restart_preview_playback(self):
    self.archive_seek_var.set(0.0)
    self._gui_update_seek_label()
    return self._play_archive_selection()


def _gui_play_next_archive_entry(self):
    items = list(self.archive_tree.get_children())
    if not items:
        raise ToolError('No CombinedAudio rows are loaded.')
    selected = self.archive_tree.selection()
    if not selected:
        next_item = items[0]
    else:
        idx = items.index(selected[0])
        next_item = items[(idx + 1) % len(items)]
    self.archive_tree.selection_set(next_item)
    self.archive_tree.focus(next_item)
    self.archive_tree.see(next_item)
    self._on_archive_tree_select()
    return self._play_archive_selection()


def _gui_reload_archive_table(self):
    self._archive_preview_cache.clear()
    return self._load_archive_table()


def _gui_make_diff_summary(self, before_info: dict, after_info: dict, table_index: int, name: str, current_entry_size: int, new_blob_size: int):
    old_end = current_entry_size
    shifts = 'yes' if new_blob_size != current_entry_size else 'no'
    return (
        f'Replace CombinedAudio entry #{table_index} with {name}?\n\n'
        f'Old size vs new size: {current_entry_size} -> {new_blob_size} bytes\n'
        f'Old mode vs new mode: {before_info.get("mode_name")} -> {after_info.get("mode_name")}\n'
        f'Sample rate: {before_info.get("sample_rate")} -> {after_info.get("sample_rate")}\n'
        f'Channel count: {before_info.get("channels")} -> {after_info.get("channels")}\n'
        f'Name: {before_info.get("embedded_name", "")} -> {after_info.get("embedded_name", "")}\n'
        f'Whether offsets shifted: {shifts}'
    )


def _gui_replace_archive_selection(self):
    combined_audio_path = Path(self.archive_path.get())
    table_index = self._gui_get_selected_archive_table_index()
    replacement = filedialog.askopenfilename(filetypes=(("Supported Audio/FSB", "*.fsb *.wav *.wave *.dsp"), ("All Files", "*.*")))
    if not replacement:
        return 'Replacement canceled.'
    preview = self._gui_prepare_preview_for_table_index(table_index)
    template_fsb = preview['fsb_bytes']
    new_blob = self.backend.build_replacement_fsb_from_source(template_fsb, Path(replacement))
    new_info = self.backend.inspect_fsb_bytes_detailed(new_blob)
    current_size = len(template_fsb)
    diff_text = self._gui_make_diff_summary(preview['fsb_info'], new_info, table_index, Path(replacement).name, current_size, len(new_blob))
    if not messagebox.askyesno('Replacement diff', diff_text):
        return 'Replacement canceled after diff review.'
    output_text = self.archive_out_path.get().strip()
    output_path = Path(output_text) if output_text else combined_audio_path
    result = self.backend.update_combinedaudio_entry(combined_audio_path, table_index, new_blob=new_blob, output_path=output_path)
    self.archive_path.set(str(result))
    self._archive_preview_cache.clear()
    self._load_archive_table()
    return f'Replaced CombinedAudio table entry #{table_index} using {Path(replacement).name} and reloaded: {result}'


def _gui_apply_loop_metadata_to_selected(self):
    table_index = self._gui_get_selected_archive_table_index()
    preview = self._gui_prepare_preview_for_table_index(table_index)
    sample_rate = preview['fsb_info']['sample_rate']
    start_text = self.loop_start_samples_var.get().strip()
    end_text = self.loop_end_samples_var.get().strip()
    if not start_text or not end_text:
        start_s = float(self.loop_start_seconds_var.get().strip() or '0')
        end_s = float(self.loop_end_seconds_var.get().strip() or '0')
        loop_start = _ca_seconds_to_samples(start_s, sample_rate)
        loop_end = _ca_seconds_to_samples(end_s, sample_rate)
    else:
        loop_start = int(start_text)
        loop_end = int(end_text)
    if not (0 <= loop_start < loop_end <= preview['fsb_info']['sample_count']):
        raise ToolError('Loop points must satisfy 0 <= start < end <= sample_count.')
    patched = self.backend.patch_fsb_loop_bytes(preview['fsb_bytes'], loop_start, loop_end)
    combined_audio_path = Path(self.archive_path.get())
    output_text = self.archive_out_path.get().strip()
    output_path = Path(output_text) if output_text else combined_audio_path
    result = self.backend.update_combinedaudio_entry(combined_audio_path, table_index, new_blob=patched, output_path=output_path)
    self.archive_path.set(str(result))
    self._archive_preview_cache.clear()
    self._load_archive_table()
    return f'Applied loop edit to entry #{table_index}: {loop_start} -> {loop_end}.'


def _gui_save_selected_metadata(self):
    table_index = self._gui_get_selected_archive_table_index()
    preview = self._gui_prepare_preview_for_table_index(table_index)
    combined_audio_path = Path(self.archive_path.get())
    output_text = self.archive_out_path.get().strip()
    output_path = Path(output_text) if output_text else combined_audio_path
    new_blob = preview['fsb_bytes']
    new_name = self.meta_embedded_name_var.get().strip()
    if new_name and new_name != (preview['fsb_info'].get('embedded_name') or ''):
        new_blob = self.backend.try_patch_embedded_name(new_blob, new_name)
    new_sound_id = int(self.meta_sound_id_var.get().strip()) if self.meta_sound_id_var.get().strip() else None
    result = self.backend.update_combinedaudio_entry(combined_audio_path, table_index, new_blob=new_blob, new_sound_id=new_sound_id, output_path=output_path)
    self.archive_path.set(str(result))
    side = self._gui_load_sidecar()
    side['entries'][str(table_index)] = {'alias': self.meta_alias_var.get().strip(), 'notes': self.meta_notes_var.get().strip()}
    sidecar_path = self._gui_save_sidecar()
    self._archive_preview_cache.clear()
    self._load_archive_table()
    return f'Saved metadata for entry #{table_index}. Sidecar: {sidecar_path}'


def _gui_on_archive_drop(self, event):
    data = event.data.strip()
    if not data:
        return
    if data.startswith('{') and data.endswith('}'):
        data = data[1:-1]
    drop_path = Path(data)
    if not drop_path.exists():
        self.log(f'[Drag and Drop] Ignored drop path: {data}')
        return
    self.run_action('Drag and Drop Replace', lambda: self._replace_archive_selection_with_path(drop_path))


def _gui_replace_archive_selection_with_path(self, drop_path: Path):
    combined_audio_path = Path(self.archive_path.get())
    table_index = self._gui_get_selected_archive_table_index()
    preview = self._gui_prepare_preview_for_table_index(table_index)
    new_blob = self.backend.build_replacement_fsb_from_source(preview['fsb_bytes'], drop_path)
    new_info = self.backend.inspect_fsb_bytes_detailed(new_blob)
    diff_text = self._gui_make_diff_summary(preview['fsb_info'], new_info, table_index, drop_path.name, len(preview['fsb_bytes']), len(new_blob))
    if not messagebox.askyesno('Replacement diff', diff_text):
        return 'Drag-and-drop replacement canceled.'
    output_text = self.archive_out_path.get().strip()
    output_path = Path(output_text) if output_text else combined_audio_path
    result = self.backend.update_combinedaudio_entry(combined_audio_path, table_index, new_blob=new_blob, output_path=output_path)
    self.archive_path.set(str(result))
    self._archive_preview_cache.clear()
    self._load_archive_table()
    return f'Drag-and-drop replaced entry #{table_index} with {drop_path.name}.'


def _gui_convert_wav_to_mode2_fsb(self):
    wav_path = Path(self.convert_mode_wav_in.get().strip())
    out_path = Path(self.convert_mode2_out.get().strip() or wav_path.with_suffix('.mode2.fsb'))
    self.convert_mode2_out.set(str(out_path))
    embedded_name = self.meta_embedded_name_var.get().strip() if getattr(self, 'meta_embedded_name_var', None) else ''
    result = self.backend.build_mode2_fsb_from_wav(wav_path, out_path, embedded_name=embedded_name)
    return f'Built Mode 2 PCM16 FSB: {result}'


def _gui_convert_wav_to_mode6_fsb(self):
    tpl = Path(self.convert_template_fsb.get().strip())
    wav_path = Path(self.convert_mode_wav_in.get().strip())
    out_path = Path(self.convert_mode6_out.get().strip() or wav_path.with_suffix('.mode6.fsb'))
    self.convert_mode6_out.set(str(out_path))
    result, note = self.backend.wrap_wav_into_fsb_auto(tpl, wav_path, out_path)
    return f'Built Mode 6 GCADPCM FSB: {result} ({note})'


def _gui_build_convert_tab(self, tab):
    tab.columnconfigure(1, weight=1)
    self.decode_in = tk.StringVar()
    self.decode_out = tk.StringVar()
    self.encode_in = tk.StringVar()
    self.encode_out = tk.StringVar()
    self.raw_fsb = tk.StringVar()
    self.raw_dsp = tk.StringVar()
    self.mode2_template_name = tk.StringVar()
    self.mode2_wav = tk.StringVar()
    self.mode2_out = tk.StringVar()
    self.mode6_tpl = tk.StringVar()
    self.mode6_wav = tk.StringVar()
    self.mode6_out = tk.StringVar()
    self.add_path_row(tab, 0, 'Decode input (.fsb or .dsp)', self.decode_in, filetypes=(("Audio Files", "*.fsb *.dsp"), ("All Files", "*.*")))
    self.add_path_row(tab, 1, 'Decode output (.wav)', self.decode_out, filetypes=(("WAV Files", "*.wav"),), save=True, default_ext='.wav')
    ttk.Button(tab, text='Decode to WAV', command=lambda: self.run_action('Decode to WAV', self._decode_to_wav)).grid(row=2, column=1, sticky='w', pady=(4, 10))
    ttk.Separator(tab, orient='horizontal').grid(row=3, column=0, columnspan=3, sticky='ew', pady=10)
    self.add_path_row(tab, 4, 'Encode input (.wav)', self.encode_in, filetypes=(("WAV Files", "*.wav *.wave"), ("All Files", "*.*")))
    self.add_path_row(tab, 5, 'Encode output (.dsp)', self.encode_out, filetypes=(("DSP Files", "*.dsp"),), save=True, default_ext='.dsp')
    ttk.Button(tab, text='Encode WAV to DSP', command=lambda: self.run_action('Encode WAV to DSP', self._encode_to_dsp)).grid(row=6, column=1, sticky='w', pady=(4, 10))
    ttk.Button(tab, text='Encode WAV to Mono DSP', command=lambda: self.run_action('Encode WAV to Mono DSP', self._encode_to_mono_dsp)).grid(row=6, column=2, sticky='e', pady=(4, 10))
    ttk.Separator(tab, orient='horizontal').grid(row=7, column=0, columnspan=3, sticky='ew', pady=10)
    self.add_path_row(tab, 8, 'FSB for raw extract', self.raw_fsb, filetypes=(("FSB Files", "*.fsb"), ("All Files", "*.*")))
    self.add_path_row(tab, 9, 'DSP for raw extract', self.raw_dsp, filetypes=(("DSP Files", "*.dsp"), ("All Files", "*.*")))
    ttk.Button(tab, text='Extract raw payload from FSB', command=lambda: self.run_action('Extract Raw FSB Payload', self._extract_raw_fsb)).grid(row=10, column=1, sticky='w')
    ttk.Button(tab, text='Extract raw payload from DSP', command=lambda: self.run_action('Extract Raw DSP Payload', self._extract_raw_dsp)).grid(row=10, column=2, sticky='e')
    ttk.Separator(tab, orient='horizontal').grid(row=11, column=0, columnspan=3, sticky='ew', pady=10)
    self.add_path_row(tab, 12, 'WAV → Mode 2 PCM16 FSB source', self.mode2_wav, filetypes=(("WAV Files", "*.wav *.wave"), ("All Files", "*.*")))
    self.add_path_row(tab, 13, 'Mode 2 FSB output', self.mode2_out, filetypes=(("FSB Files", "*.fsb"),), save=True, default_ext='.fsb')
    ttk.Button(tab, text='Build Mode 2 PCM16 FSB', command=lambda: self.run_action('Build Mode 2 PCM16 FSB', lambda: self.backend.build_mode2_fsb_from_wav(Path(self.mode2_wav.get()), Path(self.mode2_out.get() or Path(self.mode2_wav.get()).with_suffix('.mode2.fsb'))))).grid(row=14, column=1, sticky='w', pady=(4, 10))
    self.add_path_row(tab, 15, 'Template FSB for Mode 6', self.mode6_tpl, filetypes=(("FSB Files", "*.fsb"), ("All Files", "*.*")))
    self.add_path_row(tab, 16, 'WAV → Mode 6 source', self.mode6_wav, filetypes=(("WAV Files", "*.wav *.wave"), ("All Files", "*.*")))
    self.add_path_row(tab, 17, 'Mode 6 FSB output', self.mode6_out, filetypes=(("FSB Files", "*.fsb"),), save=True, default_ext='.fsb')
    ttk.Button(tab, text='Build Mode 6 GCADPCM FSB', command=lambda: self.run_action('Build Mode 6 GCADPCM FSB', lambda: self.backend.wrap_wav_into_fsb_auto(Path(self.mode6_tpl.get()), Path(self.mode6_wav.get()), Path(self.mode6_out.get() or Path(self.mode6_wav.get()).with_suffix('.mode6.fsb')))[0])).grid(row=18, column=1, sticky='w', pady=(4, 0))


CAToolGUI._build_archive_tab = _gui_build_archive_tab
CAToolGUI._draw_waveform = _gui_draw_waveform
CAToolGUI._trim_wav_bytes = _gui_trim_wav_bytes
CAToolGUI._update_seek_label = _gui_update_seek_label
CAToolGUI._set_archive_summary = _gui_set_archive_summary
CAToolGUI._gui_set_archive_summary = _gui_set_archive_summary
CAToolGUI._gui_get_selected_archive_table_index = _gui_get_selected_archive_table_index
CAToolGUI._gui_load_archive_table = _gui_load_archive_table
CAToolGUI._gui_on_archive_tree_select = _gui_on_archive_tree_select
CAToolGUI._gui_cleanup_preview_temp = _gui_cleanup_preview_temp
CAToolGUI._gui_play_wav_bytes = _gui_play_wav_bytes
CAToolGUI._gui_stop_playback = _gui_stop_playback
CAToolGUI._gui_play_archive_selection = _gui_play_archive_selection
CAToolGUI._gui_play_from_seek = _gui_play_from_seek
CAToolGUI._gui_restart_preview_playback = _gui_restart_preview_playback
CAToolGUI._gui_play_next_archive_entry = _gui_play_next_archive_entry
CAToolGUI._gui_reload_archive_table = _gui_reload_archive_table
CAToolGUI._gui_replace_archive_selection = _gui_replace_archive_selection
CAToolGUI._gui_replace_archive_selection_with_path = _gui_replace_archive_selection_with_path
CAToolGUI._gui_apply_loop_metadata_to_selected = _gui_apply_loop_metadata_to_selected
CAToolGUI._gui_save_selected_metadata = _gui_save_selected_metadata
CAToolGUI._gui_on_archive_drop = _gui_on_archive_drop
CAToolGUI._gui_make_diff_summary = _gui_make_diff_summary
CAToolGUI._get_selected_archive_table_index = _gui_get_selected_archive_table_index
CAToolGUI._load_archive_table = _gui_load_archive_table
CAToolGUI._on_archive_tree_select = _gui_on_archive_tree_select
CAToolGUI._cleanup_preview_temp = _gui_cleanup_preview_temp
CAToolGUI._play_wav_bytes = _gui_play_wav_bytes
CAToolGUI._stop_playback = _gui_stop_playback
CAToolGUI._play_archive_selection = _gui_play_archive_selection
CAToolGUI._play_from_seek = _gui_play_from_seek
CAToolGUI._restart_preview_playback = _gui_restart_preview_playback
CAToolGUI._play_next_archive_entry = _gui_play_next_archive_entry
CAToolGUI._reload_archive_table = _gui_reload_archive_table
CAToolGUI._replace_archive_selection = _gui_replace_archive_selection
CAToolGUI._replace_archive_selection_with_path = _gui_replace_archive_selection_with_path
CAToolGUI._apply_loop_metadata_to_selected = _gui_apply_loop_metadata_to_selected
CAToolGUI._save_selected_metadata = _gui_save_selected_metadata
CAToolGUI._on_archive_drop = _gui_on_archive_drop
CAToolGUI._make_diff_summary = _gui_make_diff_summary
CAToolGUI._gui_init_archive_state = _gui_init_archive_state
CAToolGUI._gui_load_sidecar = _gui_load_sidecar
CAToolGUI._gui_save_sidecar = _gui_save_sidecar
CAToolGUI._gui_sidecar_path = _gui_sidecar_path
CAToolGUI._sidecar_path = _gui_sidecar_path
CAToolGUI._convert_wav_to_mode2_fsb = _gui_convert_wav_to_mode2_fsb
CAToolGUI._convert_wav_to_mode6_fsb = _gui_convert_wav_to_mode6_fsb
CAToolGUI._build_convert_tab = _gui_build_convert_tab

CAToolGUI._gui_cancel_playback_after = _gui_cancel_playback_after
CAToolGUI._gui_draw_waveform = _gui_draw_waveform
CAToolGUI._gui_prepare_preview_for_table_index = _gui_prepare_preview_for_table_index
CAToolGUI._gui_trim_wav_bytes = _gui_trim_wav_bytes
CAToolGUI._gui_update_seek_label = _gui_update_seek_label
CAToolGUI._gui_convert_wav_to_mode2_fsb = _gui_convert_wav_to_mode2_fsb
CAToolGUI._gui_convert_wav_to_mode6_fsb = _gui_convert_wav_to_mode6_fsb


def main():
    app = CAToolGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
