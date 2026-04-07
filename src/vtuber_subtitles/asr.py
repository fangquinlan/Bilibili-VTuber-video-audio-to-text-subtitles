from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FireRedTranscriberConfig:
    model_root: Path
    device: str = "auto"
    asr_batch_size: int = 1
    punc_batch_size: int = 4
    max_chunk_minutes: float = 20.0


class FireRedTranscriber:
    def __init__(self, config: FireRedTranscriberConfig) -> None:
        self.config = config
        use_gpu = config.device == "cuda" or (config.device == "auto" and _cuda_available())
        self._system = _build_system(config.model_root, use_gpu, config.asr_batch_size, config.punc_batch_size)

    def transcribe_to_text(self, wav_path: Path, *, uttid: str, chunk_dir: Path | None = None) -> dict[str, object]:
        audio_info = sf.info(str(wav_path))
        max_chunk_seconds = self.config.max_chunk_minutes * 60.0
        if audio_info.duration > max_chunk_seconds:
            result = self._transcribe_long_audio(
                wav_path,
                uttid=uttid,
                chunk_dir=chunk_dir or (wav_path.parent / f"{wav_path.stem}_chunks"),
                chunk_seconds=max_chunk_seconds,
                samplerate=audio_info.samplerate,
                channels=audio_info.channels,
            )
        else:
            result = self._system.process(str(wav_path), uttid=uttid)
        result["text"] = normalize_plain_text(str(result.get("text", "")))
        return result

    @staticmethod
    def write_outputs(result: dict[str, object], *, result_json_path: Path, subtitle_txt_path: Path) -> None:
        result_json_path.parent.mkdir(parents=True, exist_ok=True)
        subtitle_txt_path.parent.mkdir(parents=True, exist_ok=True)
        with result_json_path.open("w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        subtitle_txt_path.write_text(str(result.get("text", "")), encoding="utf-8")

    def _transcribe_long_audio(
        self,
        wav_path: Path,
        *,
        uttid: str,
        chunk_dir: Path,
        chunk_seconds: float,
        samplerate: int,
        channels: int,
    ) -> dict[str, object]:
        logger.info(
            "Chunking long audio before FireRed ASR: %s (chunk_minutes=%.2f)",
            wav_path,
            self.config.max_chunk_minutes,
        )
        chunk_dir.mkdir(parents=True, exist_ok=True)

        chunk_frames = int(chunk_seconds * samplerate)
        combined_chunks: list[dict[str, object]] = []
        combined_sentences: list[dict[str, object]] = []
        combined_words: list[dict[str, object]] = []
        combined_vad_segments: list[list[int]] = []
        combined_texts: list[str] = []

        try:
            with sf.SoundFile(str(wav_path), "r") as source:
                chunk_index = 0
                start_frame = 0
                while True:
                    chunk_audio = source.read(chunk_frames, dtype="int16", always_2d=True)
                    if len(chunk_audio) == 0:
                        break

                    chunk_index += 1
                    chunk_start_ms = int(start_frame * 1000 / samplerate)
                    chunk_end_ms = int((start_frame + len(chunk_audio)) * 1000 / samplerate)
                    chunk_path = chunk_dir / f"{chunk_index:05d}.wav"
                    with sf.SoundFile(
                        str(chunk_path),
                        "w",
                        samplerate=samplerate,
                        channels=channels,
                        subtype="PCM_16",
                    ) as sink:
                        sink.write(chunk_audio)

                    chunk_result = self._system.process(str(chunk_path), uttid=f"{uttid}_chunk{chunk_index:05d}")
                    chunk_text = normalize_plain_text(str(chunk_result.get("text", "")))
                    if chunk_text:
                        combined_texts.append(chunk_text)

                    for sentence in chunk_result.get("sentences", []):
                        combined_sentences.append(_offset_time_fields(sentence, chunk_start_ms))
                    for word in chunk_result.get("words", []):
                        combined_words.append(_offset_time_fields(word, chunk_start_ms))
                    for start_ms, end_ms in chunk_result.get("vad_segments_ms", []):
                        combined_vad_segments.append([start_ms + chunk_start_ms, end_ms + chunk_start_ms])

                    combined_chunks.append(
                        {
                            "chunk_index": chunk_index,
                            "start_ms": chunk_start_ms,
                            "end_ms": chunk_end_ms,
                            "text": chunk_text,
                        }
                    )
                    start_frame += len(chunk_audio)
        finally:
            shutil.rmtree(chunk_dir, ignore_errors=True)

        return {
            "uttid": uttid,
            "text": "\n".join(combined_texts),
            "sentences": combined_sentences,
            "vad_segments_ms": combined_vad_segments,
            "dur_s": round(combined_chunks[-1]["end_ms"] / 1000, 3) if combined_chunks else 0.0,
            "words": combined_words,
            "wav_path": str(wav_path),
            "chunked": True,
            "chunk_count": len(combined_chunks),
            "chunk_minutes": self.config.max_chunk_minutes,
            "chunks": combined_chunks,
        }


def normalize_plain_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:，。！？；：])", r"\1", text)
    return text.strip()


def _offset_time_fields(entry: dict[str, object], offset_ms: int) -> dict[str, object]:
    updated = dict(entry)
    if "start_ms" in updated:
        updated["start_ms"] = int(updated["start_ms"]) + offset_ms
    if "end_ms" in updated:
        updated["end_ms"] = int(updated["end_ms"]) + offset_ms
    return updated


def _build_system(model_root: Path, use_gpu: bool, asr_batch_size: int, punc_batch_size: int):
    from fireredasr2s import FireRedAsr2System, FireRedAsr2SystemConfig
    from fireredasr2s.fireredasr2 import FireRedAsr2Config
    from fireredasr2s.fireredlid import FireRedLidConfig
    from fireredasr2s.fireredpunc import FireRedPuncConfig
    from fireredasr2s.fireredvad import FireRedVadConfig

    config = FireRedAsr2SystemConfig(
        vad_model_dir=str(model_root / "FireRedVAD" / "VAD"),
        lid_model_dir=str(model_root / "FireRedLID"),
        asr_type="aed",
        asr_model_dir=str(model_root / "FireRedASR2-AED"),
        punc_model_dir=str(model_root / "FireRedPunc"),
        vad_config=FireRedVadConfig(use_gpu=use_gpu),
        lid_config=FireRedLidConfig(use_gpu=use_gpu, use_half=False),
        asr_config=FireRedAsr2Config(
            use_gpu=use_gpu,
            use_half=False,
            beam_size=3,
            nbest=1,
            decode_max_len=0,
            softmax_smoothing=1.25,
            aed_length_penalty=0.6,
            eos_penalty=1.0,
            return_timestamp=False,
        ),
        punc_config=FireRedPuncConfig(use_gpu=use_gpu),
        asr_batch_size=asr_batch_size,
        punc_batch_size=punc_batch_size,
        enable_vad=True,
        enable_lid=True,
        enable_punc=True,
    )
    logger.info("Loading FireRedASR2-AED system (use_gpu=%s) from %s", use_gpu, model_root)
    return FireRedAsr2System(config)


def _cuda_available() -> bool:
    import torch

    return torch.cuda.is_available()
