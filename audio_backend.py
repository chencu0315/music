from __future__ import annotations

from dataclasses import dataclass, field
import io
from pathlib import Path
import math
import struct
import subprocess
import wave

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover
    imageio_ffmpeg = None


class AudioFormatError(Exception):
    """Raised when the WAV format cannot be processed by this prototype."""


def format_seconds(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:04.1f}"
    return f"{minutes:02d}:{secs:04.1f}"


def parse_time_text(value: str) -> float:
    text = value.strip()
    if not text:
        raise ValueError("时间不能为空")

    if ":" not in text:
        seconds = float(text)
        if seconds < 0:
            raise ValueError("时间不能为负数")
        return seconds

    parts = text.split(":")
    if len(parts) == 2:
        minutes = int(parts[0])
        seconds = float(parts[1])
        total = minutes * 60 + seconds
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        total = hours * 3600 + minutes * 60 + seconds
    else:
        raise ValueError("时间格式无效，应为 秒 / MM:SS / HH:MM:SS")

    if total < 0:
        raise ValueError("时间不能为负数")
    return total


def _sample_limits(sample_width: int) -> tuple[int, int, int]:
    if sample_width < 1 or sample_width > 4:
        raise AudioFormatError(f"暂不支持 {sample_width * 8} bit PCM")

    if sample_width == 1:
        return -128, 127, 127

    bits = sample_width * 8
    maximum = (1 << (bits - 1)) - 1
    minimum = -(1 << (bits - 1))
    normalizer = max(abs(minimum), abs(maximum))
    return minimum, maximum, normalizer


def _decode_pcm(raw_data: bytes, sample_width: int) -> list[int]:
    if sample_width == 1:
        return [byte - 128 for byte in raw_data]

    if sample_width == 2:
        count = len(raw_data) // 2
        return list(struct.unpack("<" + "h" * count, raw_data))

    if sample_width == 3:
        samples: list[int] = []
        for index in range(0, len(raw_data), 3):
            chunk = raw_data[index:index + 3]
            value = chunk[0] | (chunk[1] << 8) | (chunk[2] << 16)
            if value & 0x800000:
                value -= 1 << 24
            samples.append(value)
        return samples

    count = len(raw_data) // 4
    return list(struct.unpack("<" + "i" * count, raw_data))


def _read_wav_bytes(wav_bytes: bytes) -> tuple[int, int, int, bytes]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        if wav_file.getcomptype() != "NONE":
            raise AudioFormatError("仅支持未压缩 PCM 音频流")

        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        raw_frames = wav_file.readframes(wav_file.getnframes())

    return sample_rate, channels, sample_width, raw_frames


def _require_ffmpeg() -> str:
    if imageio_ffmpeg is None:
        raise AudioFormatError("MP3 支持未就绪，请先安装 imageio-ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


def _encode_pcm(samples: list[int], sample_width: int) -> bytes:
    minimum, maximum, _ = _sample_limits(sample_width)

    if sample_width == 1:
        return bytes(max(0, min(255, sample + 128)) for sample in samples)

    if sample_width == 2:
        clamped = [max(minimum, min(maximum, sample)) for sample in samples]
        return struct.pack("<" + "h" * len(clamped), *clamped)

    if sample_width == 3:
        data = bytearray()
        for sample in samples:
            value = max(minimum, min(maximum, sample))
            if value < 0:
                value += 1 << 24
            data.extend((value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF))
        return bytes(data)

    clamped = [max(minimum, min(maximum, sample)) for sample in samples]
    return struct.pack("<" + "i" * len(clamped), *clamped)


@dataclass
class AudioClip:
    sample_rate: int
    channels: int
    sample_width: int
    samples: list[int]
    source_path: str | None = None
    display_name: str = "未命名音频"
    _peak_cache: list[float] | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_file(cls, path: str | Path) -> "AudioClip":
        audio_path = Path(path)
        extension = audio_path.suffix.lower()
        if extension == ".wav":
            return cls.from_wav(audio_path)
        if extension == ".mp3":
            return cls.from_mp3(audio_path)
        raise AudioFormatError("当前仅支持导入 WAV 或 MP3 文件")

    @classmethod
    def from_wav(cls, path: str | Path) -> "AudioClip":
        wav_path = Path(path)
        with wave.open(str(wav_path), "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                raise AudioFormatError("仅支持未压缩 PCM WAV 文件")

            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            raw_frames = wav_file.readframes(wav_file.getnframes())

        samples = _decode_pcm(raw_frames, sample_width)
        return cls(
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            samples=samples,
            source_path=str(wav_path),
            display_name=wav_path.name,
        )

    @classmethod
    def from_mp3(cls, path: str | Path) -> "AudioClip":
        mp3_path = Path(path)
        ffmpeg_exe = _require_ffmpeg()
        process = subprocess.run(
            [ffmpeg_exe, "-v", "error", "-i", str(mp3_path), "-f", "wav", "pipe:1"],
            capture_output=True,
            check=False,
        )
        if process.returncode != 0 or not process.stdout:
            message = process.stderr.decode("utf-8", errors="ignore").strip() or "ffmpeg 解码失败"
            raise AudioFormatError(f"无法读取 MP3：{message}")

        sample_rate, channels, sample_width, raw_frames = _read_wav_bytes(process.stdout)
        samples = _decode_pcm(raw_frames, sample_width)
        return cls(
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            samples=samples,
            source_path=str(mp3_path),
            display_name=mp3_path.name,
        )

    @property
    def frame_count(self) -> int:
        return len(self.samples) // max(self.channels, 1)

    @property
    def duration(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return self.frame_count / self.sample_rate

    @property
    def bit_depth(self) -> int:
        return self.sample_width * 8

    @property
    def channel_label(self) -> str:
        if self.channels == 1:
            return "单声道"
        if self.channels == 2:
            return "立体声"
        return f"{self.channels} 声道"

    def clone(self) -> "AudioClip":
        return AudioClip(
            sample_rate=self.sample_rate,
            channels=self.channels,
            sample_width=self.sample_width,
            samples=self.samples.copy(),
            source_path=self.source_path,
            display_name=self.display_name,
        )

    def time_to_frame(self, seconds: float) -> int:
        seconds = max(0.0, min(seconds, self.duration))
        return int(round(seconds * self.sample_rate))

    def frame_to_time(self, frame_index: int) -> float:
        frame_index = max(0, min(frame_index, self.frame_count))
        if self.sample_rate <= 0:
            return 0.0
        return frame_index / self.sample_rate

    def to_bytes(self, start_frame: int = 0, end_frame: int | None = None) -> bytes:
        end_frame = self.frame_count if end_frame is None else end_frame
        start_frame = max(0, min(start_frame, self.frame_count))
        end_frame = max(start_frame, min(end_frame, self.frame_count))
        start_index = start_frame * self.channels
        end_index = end_frame * self.channels
        return _encode_pcm(self.samples[start_index:end_index], self.sample_width)

    def export_wav(self, path: str | Path, start_frame: int = 0, end_frame: int | None = None) -> None:
        wav_path = Path(path)
        wav_path.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(wav_path), "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.sample_width)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(self.to_bytes(start_frame, end_frame))

    def to_wav_bytes(self, start_frame: int = 0, end_frame: int | None = None) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.sample_width)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(self.to_bytes(start_frame, end_frame))
        return buffer.getvalue()

    def export(self, path: str | Path, start_frame: int = 0, end_frame: int | None = None) -> None:
        output_path = Path(path)
        extension = output_path.suffix.lower()
        if extension == ".wav":
            self.export_wav(output_path, start_frame, end_frame)
            return

        if extension == ".mp3":
            ffmpeg_exe = _require_ffmpeg()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            wav_bytes = self.to_wav_bytes(start_frame, end_frame)
            process = subprocess.run(
                [
                    ffmpeg_exe,
                    "-y",
                    "-v",
                    "error",
                    "-f",
                    "wav",
                    "-i",
                    "pipe:0",
                    "-b:a",
                    "192k",
                    str(output_path),
                ],
                input=wav_bytes,
                capture_output=True,
                check=False,
            )
            if process.returncode != 0:
                message = process.stderr.decode("utf-8", errors="ignore").strip() or "ffmpeg 编码失败"
                raise AudioFormatError(f"无法导出 MP3：{message}")
            return

        raise AudioFormatError("当前仅支持导出 WAV 或 MP3 文件")

    def cut_frames(self, start_frame: int, end_frame: int) -> "AudioClip":
        start_frame = max(0, min(start_frame, self.frame_count))
        end_frame = max(start_frame, min(end_frame, self.frame_count))
        start_index = start_frame * self.channels
        end_index = end_frame * self.channels
        new_samples = self.samples[:start_index] + self.samples[end_index:]
        return AudioClip(
            sample_rate=self.sample_rate,
            channels=self.channels,
            sample_width=self.sample_width,
            samples=new_samples,
            source_path=self.source_path,
            display_name=self.display_name,
        )

    def slice_frames(self, start_frame: int, end_frame: int) -> "AudioClip":
        start_frame = max(0, min(start_frame, self.frame_count))
        end_frame = max(start_frame, min(end_frame, self.frame_count))
        start_index = start_frame * self.channels
        end_index = end_frame * self.channels
        return AudioClip(
            sample_rate=self.sample_rate,
            channels=self.channels,
            sample_width=self.sample_width,
            samples=self.samples[start_index:end_index],
            source_path=self.source_path,
            display_name=self.display_name,
        )

    def apply_volume(self, factor: float) -> "AudioClip":
        if factor <= 0:
            raise ValueError("音量倍数必须大于 0")

        minimum, maximum, _ = _sample_limits(self.sample_width)
        scaled = [
            max(minimum, min(maximum, int(round(sample * factor))))
            for sample in self.samples
        ]
        return AudioClip(
            sample_rate=self.sample_rate,
            channels=self.channels,
            sample_width=self.sample_width,
            samples=scaled,
            source_path=self.source_path,
            display_name=self.display_name,
        )

    def change_speed(self, factor: float) -> "AudioClip":
        if factor <= 0:
            raise ValueError("变速倍数必须大于 0")

        new_rate = max(1, int(round(self.sample_rate * factor)))
        return AudioClip(
            sample_rate=new_rate,
            channels=self.channels,
            sample_width=self.sample_width,
            samples=self.samples.copy(),
            source_path=self.source_path,
            display_name=self.display_name,
        )

    def merge(self, other: "AudioClip") -> "AudioClip":
        if self.channels != other.channels:
            raise AudioFormatError("合并失败：两个 WAV 的声道数不同")
        if self.sample_width != other.sample_width:
            raise AudioFormatError("合并失败：两个 WAV 的位深不同")
        if self.sample_rate != other.sample_rate:
            raise AudioFormatError("合并失败：两个 WAV 的采样率不同")

        return AudioClip(
            sample_rate=self.sample_rate,
            channels=self.channels,
            sample_width=self.sample_width,
            samples=self.samples + other.samples,
            source_path=self.source_path,
            display_name=self.display_name,
        )

    def _ensure_peak_cache(self, target_points: int = 4096) -> None:
        if self._peak_cache is not None:
            return

        if self.frame_count == 0:
            self._peak_cache = [0.0]
            return

        _, _, normalizer = _sample_limits(self.sample_width)
        bucket_size = max(1, math.ceil(self.frame_count / max(target_points, 1)))
        peaks: list[float] = []

        for frame_start in range(0, self.frame_count, bucket_size):
            frame_end = min(frame_start + bucket_size, self.frame_count)
            peak = 0.0
            sample_index = frame_start * self.channels
            end_index = frame_end * self.channels

            while sample_index < end_index:
                if self.channels == 1:
                    amplitude = abs(self.samples[sample_index])
                    sample_index += 1
                else:
                    total = 0.0
                    for channel_offset in range(self.channels):
                        total += abs(self.samples[sample_index + channel_offset])
                    amplitude = total / self.channels
                    sample_index += self.channels

                if amplitude > peak:
                    peak = amplitude

            peaks.append(min(1.0, peak / normalizer))

        self._peak_cache = peaks or [0.0]

    def get_waveform_peaks(self, point_count: int) -> list[float]:
        point_count = max(1, point_count)
        self._ensure_peak_cache()
        assert self._peak_cache is not None

        cache = self._peak_cache
        if len(cache) == point_count:
            return cache.copy()

        if point_count > len(cache):
            return [
                cache[min(len(cache) - 1, int(index * len(cache) / point_count))]
                for index in range(point_count)
            ]

        span = len(cache) / point_count
        peaks: list[float] = []
        for index in range(point_count):
            start = int(index * span)
            end = max(start + 1, int((index + 1) * span))
            peaks.append(max(cache[start:end]))
        return peaks
