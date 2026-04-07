from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from transformers import AutoModel

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VocalSeparatorConfig:
    model_dir: Path
    device: str = "auto"
    chunk_seconds: float = 30.0
    overlap_seconds: float = 2.0
    batch_size: int = 2


class VocalSeparator:
    def __init__(self, config: VocalSeparatorConfig) -> None:
        self.config = config
        self.device = _resolve_device(config.device)
        torch_dtype = torch.bfloat16 if self.device.type == "cuda" else torch.float32
        logger.info("Loading Mini-BS-RoFormer-V2 on %s from %s", self.device, config.model_dir)
        self.model = AutoModel.from_pretrained(
            str(config.model_dir),
            trust_remote_code=True,
            torch_dtype=torch_dtype,
        )
        self.model.to(self.device)
        self.model.eval()

    @torch.inference_mode()
    def separate_to_vocals(self, input_wav: Path, output_wav: Path, overwrite: bool) -> Path:
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        if output_wav.exists() and not overwrite:
            return output_wav

        with sf.SoundFile(str(input_wav), "r") as source:
            sample_rate = source.samplerate
            channels = source.channels
            total_frames = len(source)
            if sample_rate != 44100:
                raise ValueError(f"Separator input must be 44.1kHz WAV, got {sample_rate} Hz for {input_wav}")
            if channels != 2:
                raise ValueError(f"Separator input must be stereo WAV, got {channels} channel(s) for {input_wav}")

            chunk_frames = int(self.config.chunk_seconds * sample_rate)
            overlap_frames = int(self.config.overlap_seconds * sample_rate)
            if chunk_frames <= overlap_frames:
                raise ValueError("chunk_seconds must be larger than overlap_seconds")
            step_frames = chunk_frames - overlap_frames
            total_chunks = max(1, (total_frames + step_frames - 1) // step_frames)

            prev_tail: np.ndarray | None = None
            with sf.SoundFile(
                str(output_wav),
                "w",
                samplerate=sample_rate,
                channels=channels,
                subtype="PCM_16",
            ) as sink:
                chunk_index = 0
                for start_frame in range(0, total_frames, step_frames):
                    chunk_index += 1
                    source.seek(start_frame)
                    chunk = source.read(chunk_frames, dtype="float32", always_2d=True)
                    valid_frames = len(chunk)
                    if valid_frames == 0:
                        break
                    if valid_frames < chunk_frames:
                        padding = np.zeros((chunk_frames - valid_frames, channels), dtype=np.float32)
                        chunk = np.concatenate([chunk, padding], axis=0)

                    vocals = self._run_model(chunk)[:valid_frames]
                    if prev_tail is None:
                        if valid_frames <= step_frames:
                            sink.write(vocals)
                            prev_tail = None
                        else:
                            sink.write(vocals[:step_frames])
                            prev_tail = vocals[step_frames:valid_frames]
                    else:
                        head_frames = min(len(prev_tail), valid_frames)
                        if head_frames:
                            sink.write(_crossfade(prev_tail[:head_frames], vocals[:head_frames]))

                        if valid_frames > step_frames:
                            sink.write(vocals[head_frames:step_frames])
                            prev_tail = vocals[step_frames:valid_frames]
                        else:
                            sink.write(vocals[head_frames:valid_frames])
                            prev_tail = None

                    if self.device.type == "cuda":
                        torch.cuda.empty_cache()
                    logger.info("Separated chunk %d/%d for %s", chunk_index, total_chunks, input_wav.name)

                if prev_tail is not None and len(prev_tail):
                    sink.write(prev_tail)

        return output_wav

    def _run_model(self, chunk: np.ndarray) -> np.ndarray:
        waveform = torch.from_numpy(chunk.T).to(self.device).contiguous()
        result = self.model.separate(
            waveform,
            batch_size=self.config.batch_size,
            verbose=False,
        )
        return result[3].detach().float().cpu().numpy().T


def _crossfade(previous: np.ndarray, current: np.ndarray) -> np.ndarray:
    if len(previous) != len(current):
        raise ValueError("Crossfade chunks must have the same length.")
    if len(previous) == 1:
        return (previous + current) / 2

    fade_in = np.linspace(0.0, 1.0, num=len(previous), dtype=np.float32)[:, None]
    return previous * (1.0 - fade_in) + current * fade_in


def _resolve_device(device: str) -> torch.device:
    if device == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device)
