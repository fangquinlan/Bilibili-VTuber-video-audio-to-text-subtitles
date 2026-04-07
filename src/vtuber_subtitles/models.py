from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from huggingface_hub import snapshot_download

logger = logging.getLogger(__name__)

SEPARATOR_REPO_ID = "HiDolen/Mini-BS-RoFormer-V2-46.8M"
FIRERED_HF_MODELS = {
    "FireRedASR2-AED": "FireRedTeam/FireRedASR2-AED",
    "FireRedVAD": "FireRedTeam/FireRedVAD",
    "FireRedLID": "FireRedTeam/FireRedLID",
    "FireRedPunc": "FireRedTeam/FireRedPunc",
}
FIRERED_MODELSCOPE_MODELS = {
    "FireRedASR2-AED": "xukaituo/FireRedASR2-AED",
    "FireRedVAD": "xukaituo/FireRedVAD",
    "FireRedLID": "xukaituo/FireRedLID",
    "FireRedPunc": "xukaituo/FireRedPunc",
}
FIRERED_EXPECTED_FILES = {
    "FireRedASR2-AED": ["model.pth.tar", "dict.txt", "train_bpe1000.model", "cmvn.ark"],
    "FireRedVAD": ["VAD/model.pth.tar", "VAD/cmvn.ark"],
    "FireRedLID": ["model.pth.tar", "dict.txt", "cmvn.ark"],
    "FireRedPunc": ["model.pth.tar", "vocab.txt"],
}


def ensure_separator_model(model_dir: Path, repo_id: str = SEPARATOR_REPO_ID, token: str | None = None) -> Path:
    model_dir.mkdir(parents=True, exist_ok=True)
    if (model_dir / "config.json").exists():
        return model_dir

    logger.info("Downloading separator model %s into %s", repo_id, model_dir)
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(model_dir),
        local_dir_use_symlinks=False,
        token=token,
    )
    return model_dir


def ensure_firered_models(
    model_root: Path,
    *,
    provider: str = "auto",
    token: str | None = None,
) -> Path:
    model_root.mkdir(parents=True, exist_ok=True)
    for model_name in FIRERED_HF_MODELS:
        target_dir = model_root / model_name
        if _has_expected_files(target_dir, FIRERED_EXPECTED_FILES[model_name]):
            continue

        if provider in {"auto", "modelscope"} and _modelscope_available():
            try:
                _download_from_modelscope(FIRERED_MODELSCOPE_MODELS[model_name], target_dir)
                continue
            except Exception as exc:  # pragma: no cover
                if provider == "modelscope":
                    raise
                logger.warning("ModelScope download for %s failed, falling back to Hugging Face: %s", model_name, exc)

        _download_from_huggingface(FIRERED_HF_MODELS[model_name], target_dir, token=token)
    return model_root


def _download_from_huggingface(repo_id: str, target_dir: Path, token: str | None = None) -> None:
    logger.info("Downloading %s from Hugging Face into %s", repo_id, target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
        token=token,
    )


def _download_from_modelscope(repo_id: str, target_dir: Path) -> None:
    logger.info("Downloading %s from ModelScope into %s", repo_id, target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    from modelscope.hub.snapshot_download import snapshot_download as ms_snapshot_download

    ms_snapshot_download(model_id=repo_id, local_dir=str(target_dir))


def _has_expected_files(target_dir: Path, expected_files: list[str]) -> bool:
    return all((target_dir / relative_path).exists() for relative_path in expected_files)


def _modelscope_available() -> bool:
    return importlib.util.find_spec("modelscope") is not None
