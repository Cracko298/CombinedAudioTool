## Deciphering CombinedAudio's Header/TOC and Automating Variable-Length Rebuilds with CATool

----

## Observed archive structure
- The header/toc size is calculated by this formula: `header_size = 4 + entry_count * 12`.
- The outer CombinedAudio header is consistent and unusually simple. It has no visible archive magic, no visible version field, and no visible outer checksum.
- The header begins with a 32-bit little-endian entry count, followed immediately by a flat table of 12-byte records.
- In the archive, the table covers 558 segments, and the sum of all stored sizes exactly equals the file length minus the computed header size.
- Every stored segment begins at `header_size + offset`, every stored segment starts with `FSB5`, and every stored segment size matches the exact total length implied by its inner FSB header.
- And validate the rebuilt archive by confirming that every entry points to `FSB5` at `header_size + offset` and that each segment length matches the inner FSB’s own declared total size.
- We can parse the archive header first, then extract and rebuild by **header entries**, not by scanning for `FSB5`, like CATool did previously.

### Hex-offset table

The following table is derived from direct analysis of `CombinedAudio.bin`.

| Offset | Size | Type | Semantics | Behavior |
|---|---:|---|---|---|
| `0x0000` | 4 | `u32`, little-endian | entry count | `0x0000022E` = 558 |
| `0x0004 + n*0x0C` | 4 | `u32`, little-endian | SoundID/Hash | Wnique per entry; header-sorted ascending; not file-order |
| `0x0008 + n*0x0C` | 4 | `u32`, little-endian | Relative FSB Offset from EOH (End-of-Header) | When sorted, runs from `0x00000000` -> `0x00A6F7E0`. |
| `0x000C + n*0x0C` | 4 | `u32`, little-endian | Stored size of this FSB blob | Exact segment size in bytes; all sample values are `0x20` aligned |

### The Real TOC/Header formula is as such:
```text
header_size = 4 + (entry_count * 12)
```

### For the `CombinedAudio.bin` archive specifically:
```text
entry_count = 558
header_size = 4 + 558 * 12 = 6700 = 0x1A2C
```

----

- A raw hex example from the `CombinedAudio` header shows the pattern immediately:
```text
0000  2e 02 00 00 74 f9 d5 00 e0 1d 2d 00 00 fd 00 00
      ^ count=0x022e  ^ id/key=0x00d5f974 ^ off=0x002d1de0 ^ size=0x0000fd00
```

- The first field is best interpreted as a lookup key rather than a position. 
- Those values are unique and sorted ascending in header order, while the actual FSB file order is recovered only by sorting records by the second field.
- A second important observation is that the archive header is **relative**, not absolute. The real file start for each FSB is:
```text
absolute_fsb_start = header_size + relative_offset
```

- That explains why copying `header_data.bin` unchanged only works when every rebuilt segment stays exactly the same size. 
- Change one stored FSB length and every later relative offset becomes stale.

----

## Relationship to FSB and DSP

- The outer archive only stores where each segment is and how large it is. Playback metadata lives inside the stored FSB and DSP layers, not in the outer archive header. 
- The reverse-engineered FSB5 references show a file header with `sampleHeaderSize`, `nameTableSize`, and `dataSize`, followed by packed per-sample headers and metadata chunks such as `CHANNELS`, `FREQUENCY`, `LOOP`, and `DSPCOEFF`. 
- Public DSP references show a 0x60-byte big-endian header with `num_samples`, `num_adpcm_nibbles`, `sample_rate`, loop offsets, coefficients, and decoder state.

### Cross-reference table

| Layer | What it stores | Why it matters here |
|---|---|---|
| CombinedAudio.bin | outer sound key, relative FSB offset, stored FSB size | **This is the only layer you need to rewrite** to support different segment lengths in the archive |
| FSB5 | per-bank total data size, sample headers, channels/frequency/loop metadata, DSP coefficient chunks | must already be valid before you reinsert it into CombinedAudio |
| Nintendo DSP | sample count, nibble count, loop nibble offsets, coefficients, predictor/history state | relevant only when generating or validating the inner DSP stream |

- `CombinedAusio.bin` confirms this separation cleanly. For all 558 entries, `CombinedAudio.entry.size` matched:

```text
fsb_total_size = file_header_size + sampleHeaderSize + nameTableSize + dataSize
```

- Where `file_header_size` is 60 bytes for version 1 FSB5 in the public references.
- That is why the outer archive can be rebuilt safely without touching inner DSP values at all, as long as the replacement FSB is already self-consistent.

- One subtle but useful cross-reference is alignment. `CombinedAudio.bin` uses a `0x20` alignment for every stored segment offset and every stored segment size.
- Nintendo’s DSPADPCM document says ARAM DMA transfers must be **32-byte aligned** and transfer lengths must be multiples of `32-bytes`, even though individual DSP ADPCM samples are structured in `8-byte` frames. 
- That does not prove the outer archive must use `0x20` alignment, but it makes preserving 0x20 alignment the safest default way to construct it.

----

## Fields that matter for longer replacements

For **replacing existing sounds with different lengths**, only three outer-archive fields matter:

| Field | Change required when segment length changes | Notes |
|---|---|---|
| `sound_id` / key | no | preserve exactly as-is |
| `offset` | yes for the modified segment and every later segment in file order | offsets are relative to the first byte after the header |
| `size` | yes for the modified segment | should reflect the stored blob length in the archive |

- If you do **not** change the number of archive entries, the count at `0x0000` stays the same and the header size stays the same.
- That is the common case for "replace a track with a longer track."
- If you try to **add a brand-new entry**, the count changes, the header size changes, all absolute data starts move, and you still need to understand how the game maps sound IDs to playback requests.
- Because the current tooling and repo assumptions are built around a fixed 558-segment archive, adding new entries is materially riskier than replacing existing ones for now, will need more research.

| Risk | What breaks | Safe handling |
|---|---|---|
| stale outer offsets | later segments point into the wrong FSB blob | recompute every later offset during rebuild |
| stale outer size | segment truncation or overread into the next blob | rewrite the size field from the actual stored FSB length |
| missing or reordered `segment_*.fsb` files | wrong header entry gets paired with wrong content | require contiguous `segment_0` … `segment_N-1` during rebuild, or use a manifest |
| non-aligned stored sizes | possible loader or DMA assumptions violated | preserve sample behavior and auto-align stored blobs to `0x20` |
| broken inner FSB | outer archive points correctly, but inner bank is invalid | validate the FSB’s own declared total size before packing |
| changing entry count | unknown game-side lookup assumptions | avoid until the game loader is verified |

---- 

- View the workflow Flowchart [Here](https://github.com/Cracko298/CombinedAudioTool/blob/main/FLOWCHART.md)

## Code Example:

```python
from dataclasses import dataclass

COMBINED_AUDIO_ALIGNMENT = 0x20

@dataclass
class CombinedAudioEntry:
    sound_id: int
    offset: int
    size: int
    header_index: int

@dataclass
class CombinedAudioHeader:
    entry_count: int
    header_size: int
    entries: list[CombinedAudioEntry]

def parse_combined_audio_header_bytes(self, blob: bytes) -> CombinedAudioHeader:
    if len(blob) < 4:
        raise ToolError("CombinedAudio.bin is too small to contain a header.")

    entry_count = struct.unpack_from("<I", blob, 0)[0]
    if entry_count <= 0:
        raise ToolError("CombinedAudio.bin header has an invalid entry count.")

    header_size = 4 + (entry_count * 12)
    if len(blob) < header_size:
        raise ToolError(
            f"CombinedAudio.bin header declares {entry_count} entries "
            f"({header_size} bytes), but the file is only {len(blob)} bytes."
        )

    entries: list[CombinedAudioEntry] = []
    for i in range(entry_count):
        sound_id, offset, size = struct.unpack_from("<III", blob, 4 + (i * 12))
        entries.append(
            CombinedAudioEntry(
                sound_id=sound_id,
                offset=offset,
                size=size,
                header_index=i,
            )
        )

    entries_by_offset = sorted(entries, key=lambda e: e.offset)

    expected_offset = 0
    for entry in entries_by_offset:
        if entry.offset != expected_offset:
            raise ToolError(
                "CombinedAudio.bin header has a gap or overlap in the segment table "
                f"at sound ID 0x{entry.sound_id:08X}: expected offset 0x{expected_offset:X}, "
                f"found 0x{entry.offset:X}."
            )
        expected_offset += entry.size

    return CombinedAudioHeader(
        entry_count=entry_count,
        header_size=header_size,
        entries=entries,
    )

def read_combined_audio_header(self, combined_audio_path: Path) -> CombinedAudioHeader:
    self.ensure_exists(combined_audio_path)
    with open(combined_audio_path, "rb") as f:
        prefix = f.read(4)
        if len(prefix) < 4:
            raise ToolError("CombinedAudio.bin is too small.")
        entry_count = struct.unpack_from("<I", prefix, 0)[0]
        header_size = 4 + (entry_count * 12)
        f.seek(0)
        header_blob = f.read(header_size)
    return self.parse_combined_audio_header_bytes(header_blob)

def _pack_combined_audio_header(self, header: CombinedAudioHeader) -> bytes:
    out = bytearray(4 + (header.entry_count * 12))
    struct.pack_into("<I", out, 0, header.entry_count)

    for entry in header.entries:
        struct.pack_into(
            "<III",
            out,
            4 + (entry.header_index * 12),
            entry.sound_id,
            entry.offset,
            entry.size,
        )
    return bytes(out)

def _get_fsb_total_size(self, blob: bytes) -> int:
    if len(blob) < 0x3C or blob[:4] != b"FSB5":
        raise ToolError("Provided segment is not a valid FSB5 blob.")

    version, num_samples, sample_header_size, name_table_size, data_size, mode = struct.unpack_from(
        "<IIIIII", blob, 4
    )
    file_header_size = 60 if version == 1 else 64
    total_size = file_header_size + sample_header_size + name_table_size + data_size

    if total_size > len(blob):
        raise ToolError(
            f"FSB blob is truncated: header says 0x{total_size:X} bytes, "
            f"file only has 0x{len(blob):X} bytes."
        )
    return total_size

def _align_blob(self, blob: bytes, alignment: int = COMBINED_AUDIO_ALIGNMENT) -> bytes:
    if alignment <= 1:
        return blob
    pad = (-len(blob)) % alignment
    if not pad:
        return blob
    return blob + (b"\x00" * pad)

def _collect_segment_files_for_rebuild(self, segment_dir: Path, expected_count: int):
    segment_files = sorted(
        segment_dir.glob("segment_*.fsb"),
        key=lambda p: int(p.stem.split("_")[-1]),
    )
    if not segment_files:
        raise ToolError("No segment_*.fsb files were found in the selected folder.")

    indices = [int(p.stem.split("_")[-1]) for p in segment_files]
    expected = list(range(expected_count))
    if indices != expected:
        raise ToolError(
            "The rebuild folder must contain every segment from segment_0.fsb through "
            f"segment_{expected_count - 1}.fsb so the original archive order can be preserved."
        )
    return segment_files

def _validate_combined_audio_against_file(self, combined_audio_path: Path):
    info = self.read_combined_audio_header(combined_audio_path)
    data = Path(combined_audio_path).read_bytes()
    data_section_size = len(data) - info.header_size
    entries_by_offset = sorted(info.entries, key=lambda e: e.offset)

    total_size = sum(entry.size for entry in entries_by_offset)
    if total_size != data_section_size:
        raise ToolError(
            f"CombinedAudio.bin header accounts for 0x{total_size:X} bytes of FSB data, "
            f"but the file contains 0x{data_section_size:X} bytes after the header."
        )

    for file_index, entry in enumerate(entries_by_offset):
        abs_offset = info.header_size + entry.offset
        if data[abs_offset:abs_offset + 4] != b"FSB5":
            raise ToolError(
                f"Entry {file_index} (sound ID 0x{entry.sound_id:08X}) does not begin with FSB5 "
                f"at absolute offset 0x{abs_offset:X}."
            )
        fsb_total_size = self._get_fsb_total_size(data[abs_offset:abs_offset + entry.size])
        if fsb_total_size > entry.size:
            raise ToolError(
                f"Entry {file_index} (sound ID 0x{entry.sound_id:08X}) is truncated: "
                f"header size 0x{entry.size:X}, FSB requires 0x{fsb_total_size:X}."
            )

    return info

def extract_combined_audio(self, combined_audio_path: Path, out_dir: Path):
    self.ensure_exists(combined_audio_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = self._validate_combined_audio_against_file(combined_audio_path)
    data = Path(combined_audio_path).read_bytes()

    for file_index, entry in enumerate(sorted(info.entries, key=lambda e: e.offset)):
        abs_offset = info.header_size + entry.offset
        blob = data[abs_offset:abs_offset + entry.size]
        fsb_total_size = self._get_fsb_total_size(blob)
        (out_dir / f"segment_{file_index}.fsb").write_bytes(blob[:fsb_total_size])

    return info.entry_count

def collect_header(self, combined_audio_path: Path, out_dir: Path):
    self.ensure_exists(combined_audio_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = self.read_combined_audio_header(combined_audio_path)
    with open(combined_audio_path, "rb") as f:
        header = f.read(info.header_size)

    out_path = out_dir / "header_data.bin"
    out_path.write_bytes(header)
    return out_path

def rebuild_combined_audio(self, segment_dir: Path, output_path: Path):
    header_path = segment_dir / "header_data.bin"
    self.ensure_exists(header_path)

    original_header = self.parse_combined_audio_header_bytes(header_path.read_bytes())
    segment_files = self._collect_segment_files_for_rebuild(segment_dir, original_header.entry_count)

    new_entries = list(original_header.entries)
    payloads: list[bytes] = []
    running_offset = 0

    file_order_entries = sorted(original_header.entries, key=lambda e: e.offset)

    for entry, seg_path in zip(file_order_entries, segment_files):
        blob = seg_path.read_bytes()
        fsb_total_size = self._get_fsb_total_size(blob)

        blob = blob[:fsb_total_size]
        blob = self._align_blob(blob, COMBINED_AUDIO_ALIGNMENT)

        new_entries[entry.header_index] = CombinedAudioEntry(
            sound_id=entry.sound_id,
            offset=running_offset,
            size=len(blob),
            header_index=entry.header_index,
        )
        payloads.append(blob)
        running_offset += len(blob)

    rebuilt_header = CombinedAudioHeader(
        entry_count=original_header.entry_count,
        header_size=4 + (original_header.entry_count * 12),
        entries=new_entries,
    )
    header_blob = self._pack_combined_audio_header(rebuilt_header)

    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with open(tmp_path, "wb") as out:
        out.write(header_blob)
        for blob in payloads:
            out.write(blob)

    self._validate_combined_audio_against_file(tmp_path)

    if output_path.exists():
        backup_path = output_path.with_suffix(output_path.suffix + ".bak")
        shutil.copy2(output_path, backup_path)

    tmp_path.replace(output_path)
    return output_path

def get_metadata(self, combined_audio_path: Path):
    info = self._validate_combined_audio_against_file(combined_audio_path)
    counts = self.count_specific_bytes(combined_audio_path)
    return {
        "header_length": info.header_size,
        "audio_files": info.entry_count,
        **counts,
    }
```

## Important Invariant(s):

```python
def test_parse_sample_header(backend, combined_path):
    info = backend.read_combined_audio_header(combined_path)
    assert info.entry_count == 558
    assert info.header_size == 0x1A2C

    file_order = sorted(info.entries, key=lambda e: e.offset)
    assert file_order[0].offset == 0
    assert all(file_order[i].offset + file_order[i].size == file_order[i + 1].offset
               for i in range(len(file_order) - 1))

def test_roundtrip_rebuild(backend, original_path, workdir):
    backend.extract_combined_audio(original_path, workdir)
    backend.collect_header(original_path, workdir)
    rebuilt = workdir / "rebuilt.bin"
    backend.rebuild_combined_audio(workdir, rebuilt)
    assert rebuilt.read_bytes() == original_path.read_bytes()

def test_grow_first_segment_shifts_following_offsets(backend, original_path, workdir):
    backend.extract_combined_audio(original_path, workdir)
    backend.collect_header(original_path, workdir)

    seg0 = workdir / "segment_0.fsb"
    blob = bytearray(seg0.read_bytes())
    data_size = struct.unpack_from("<I", blob, 0x14)[0]
    struct.pack_into("<I", blob, 0x14, data_size + 0x20)
    blob += b"\x00" * 0x20
    seg0.write_bytes(blob)

    rebuilt = workdir / "rebuilt_plus20.bin"
    backend.rebuild_combined_audio(workdir, rebuilt)

    old_info = backend.read_combined_audio_header(original_path)
    new_info = backend.read_combined_audio_header(rebuilt)

    old_file = sorted(old_info.entries, key=lambda e: e.offset)
    new_file = sorted(new_info.entries, key=lambda e: e.offset)

    assert new_file[0].size == old_file[0].size + 0x20
    assert new_file[1].offset == old_file[1].offset + 0x20
```

----

### Hex-Dump Comparison

- This is the clearest possible demonstration of what the patch could/should do. 
- In a test below is an example...
  - The **first** stored FSB was enlarged by `0x20` bytes, the matching header entry’s size changed from `0x00009DE0` to `0x00009E00`.
  - And the **next** entry’s offset shifted from `0x00009DE0` to `0x00009E00`.

```text
Header entry for sound ID 0xE606EA8D (file-order segment 0)
before @ 0x172C: 8d ea 06 e6 00 00 00 00 e0 9d 00 00
after  @ 0x172C: 8d ea 06 e6 00 00 00 00 00 9e 00 00
                       same key        same off      size +0x20

Header entry for sound ID 0xF7CC8E18 (file-order segment 1)
before @ 0x1954: 18 8e cc f7 e0 9d 00 00 e0 e1 00 00
after  @ 0x1954: 18 8e cc f7 00 9e 00 00 e0 e1 00 00
                       same key        off  +0x20    same size
```

- This is what you want for Header and TOC Edits.
