# Bilibili VTuber Video Audio to Text Subtitles

把指定的 B 站 VTuber 录播合集一键处理为纯字幕文本：

`Bilibili 系列页 -> yt-dlp 抓音频 -> Mini-BS-RoFormer-V2 人声分离 -> FireRedASR2-AED 转写 -> txt 字幕`

默认目标合集：

- `https://space.bilibili.com/1878154667/lists/2004017?type=series`

## 适用环境

- AutoDL Linux 服务器
- 25 核 CPU + RTX 5090
- Conda 已可用
- 可以联网下载 Python 依赖与模型

## 一键运行

首次运行：

```bash
git clone https://github.com/fangquinlan/Bilibili-VTuber-video-audio-to-text-subtitles.git
cd Bilibili-VTuber-video-audio-to-text-subtitles
bash scripts/autodl_one_click.sh
```

以后复跑：

```bash
cd Bilibili-VTuber-video-audio-to-text-subtitles
bash scripts/autodl_run.sh
```

如果 Hugging Face 访问较慢，可以先设置镜像再运行：

```bash
export HF_ENDPOINT="https://hf-mirror.com"
bash scripts/autodl_one_click.sh
```

## 可选参数

直接改环境变量即可：

```bash
SERIES_URL="https://space.bilibili.com/1878154667/lists/2004017?type=series" \
OUTPUT_ROOT="$PWD/workspace/custom_run" \
MODEL_PROVIDER="auto" \
DEVICE="cuda" \
LOG_LEVEL="INFO" \
bash scripts/autodl_run.sh
```

如果 B 站页面需要登录 cookies：

```bash
bash scripts/autodl_run.sh --cookies /path/to/cookies.txt
```

只跑前 3 个视频用于试跑：

```bash
bash scripts/autodl_run.sh --limit 3
```

## 输出结构

运行完成后，主要结果在：

- `workspace/bilibili_series_2004017/subtitles/*.txt`

同时会保留中间文件，方便断点续跑：

- `workspace/bilibili_series_2004017/raw/`
- `workspace/bilibili_series_2004017/work/`
- `workspace/bilibili_series_2004017/models/`
- `workspace/bilibili_series_2004017/state/manifest.jsonl`
- `workspace/bilibili_series_2004017/state/summary.json`

每个视频在 `work/` 目录下会保留：

- 原音频转成的 `source_44100_stereo.wav`
- 分离后的人声 `vocals.wav`
- ASR 输入的 `vocals_16000_mono.wav`
- FireRed 原始结果 `result.json`
- 纯字幕文本 `subtitle.txt`

## 命令行用法

项目也提供 Python CLI：

```bash
vtuber-subtitles run-series --help
```

示例：

```bash
vtuber-subtitles run-series \
  --series-url "https://space.bilibili.com/1878154667/lists/2004017?type=series" \
  --output-root "$PWD/workspace/bilibili_series_2004017" \
  --device cuda
```

## 实现说明

- 下载：`yt-dlp`
- 人声分离：`HiDolen/Mini-BS-RoFormer-V2-46.8M`
- 语音识别：`FireRedTeam/FireRedASR2-AED`
- 辅助模块：`FireRedVAD`、`FireRedLID`、`FireRedPunc`
- FireRed 模型下载：默认 `auto`，优先尝试 ModelScope，再回退到 Hugging Face

为了适配长录播，本项目的人声分离不是整段一次性推理，而是按块切分并做 overlap-add 拼接，避免长音频直接爆显存或内存。

## 断点续跑

- 已下载的音频会记录在 `state/downloaded.txt`
- 已生成的字幕 txt 默认会跳过
- 想强制重跑时加 `--overwrite`

## 参考来源

- Mini-BS-RoFormer-V2 模型卡：<https://huggingface.co/HiDolen/Mini-BS-RoFormer-V2-46.8M>
- FireRedASR2S 官方仓库：<https://github.com/FireRedTeam/FireRedASR2S>
- FireRedASR2S README 中给出的 FireRedASR2-AED / VAD / LID / Punc 下载方式
- PyTorch 官方安装页：<https://pytorch.org/get-started/locally/>
