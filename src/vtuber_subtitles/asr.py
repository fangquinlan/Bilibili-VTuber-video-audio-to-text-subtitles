from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FireRedTranscriberConfig:
    model_root: Path
    device: str = "auto"
    asr_batch_size: int = 1
    punc_batch_size: int = 4


class FireRedTranscriber:
    def __init__(self, config: FireRedTranscriberConfig) -> None:
        self.config = config
        use_gpu = config.device == "cuda" or (config.device == "auto" and _cuda_available())
        self._system = _build_system(config.model_root, use_gpu, config.asr_batch_size, config.punc_batch_size)

    def transcribe_to_text(self, wav_path: Path, *, uttid: str) -> dict[str, object]:
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


def normalize_plain_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:，。！？；：])", r"\1", text)
    return text.strip()


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
