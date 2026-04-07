# Bilibili VTuber Video Audio to Text Subtitles

把指定的 B 站 VTuber 录播合集，或者 `input.txt` 里的任意 B 站视频链接，一键处理为纯字幕文本：

`Bilibili 系列页 -> yt-dlp 抓音频 -> Mini-BS-RoFormer-V2 人声分离 -> FireRedASR2-AED 转写 -> txt 字幕`

默认目标合集：

- `https://space.bilibili.com/1878154667/lists/2004017?type=series`

默认也会读取仓库根目录下的 `input.txt`。如果 `input.txt` 存在且里面有链接，就优先按它下载；如果为空，再回退到默认合集链接。

如果你想从某个切片员频道的搜索页自动抓链接，也支持直接给 `space/search` 页面，再按标题和时长过滤。

默认会根据机器资源自动调优：

- 24GB+ 显存并且大内存机器，默认走更激进的分离 / ASR batch
- 跑完后会在 `subtitles/` 目录下自动生成一个按顺序合并的总文本

## 适用环境

- AutoDL Linux 服务器
- 25 核 CPU + RTX 5090
- Conda 已可用
- Python 3.11+（脚本会默认创建 / 修正到 3.11 环境）
- 可以联网下载 Python 依赖与模型
- 默认无需登录 cookies；只有遇到访问限制时再传 `--cookies`

## 一键运行

首次运行：

```bash
git clone https://github.com/fangquinlan/Bilibili-VTuber-video-audio-to-text-subtitles.git
cd Bilibili-VTuber-video-audio-to-text-subtitles
python3 scripts/autodl_one_click.py
```

以后复跑：

```bash
cd Bilibili-VTuber-video-audio-to-text-subtitles
python3 scripts/autodl_run.py
```

如果 Hugging Face 访问较慢，可以先设置镜像再运行：

```bash
export HF_ENDPOINT="https://hf-mirror.com"
python3 scripts/autodl_one_click.py
```

如果你已经习惯原来的 shell 命令，也可以继续用：

```bash
bash scripts/autodl_one_click.sh
```

现在这些 `.sh` 只是 Python 包装层，不再直接依赖子脚本执行权限，所以能避开 AutoDL 上常见的 `Permission denied`。

如果 `conda create` 因为 AutoDL 机器里旧镜像源报错，脚本会自动回退到 `--override-channels -c defaults` 重试。也可以手动指定：

```bash
CONDA_CREATE_CHANNELS="defaults" python3 scripts/autodl_one_click.py
```

如果之前已经创建过 `vtuber_subtitles`，但里面还是 Python 3.10，脚本也会自动把它升级到 Python 3.11 后再继续装依赖。

## 可选参数

直接改环境变量即可：

```bash
SERIES_URL="https://space.bilibili.com/1878154667/lists/2004017?type=series" \
OUTPUT_ROOT="$PWD/workspace/custom_run" \
MODEL_PROVIDER="auto" \
DEVICE="cuda" \
LOG_LEVEL="INFO" \
python3 scripts/autodl_run.py
```

如果 B 站页面需要登录 cookies：

```bash
python3 scripts/autodl_run.py --cookies /path/to/cookies.txt
```

这份 cookies 现在也会同时用于：

- `yt-dlp` 下载受限视频
- `space/search` 自动抓链接时的 B 站搜索请求

你现在这批链接直接放进根目录的 `input.txt` 就能跑，不需要额外改代码。

如果你要从切片员频道里自动筛选，比如：

- 频道搜索页：`https://space.bilibili.com/1113769832/search?keyword=沐霂`
- 标题必须包含：`【沐霂】`
- 过滤掉 20 分钟以上视频

可以直接这样跑：

```bash
SPACE_SEARCH_URL="https://space.bilibili.com/1113769832/search?keyword=%E6%B2%90%E9%9C%82" \
TITLE_MUST_CONTAIN="【沐霂】" \
MAX_DURATION_MINUTES="20" \
python3 scripts/autodl_run.py
```

这会自动：

- 抓取该频道搜索页里的所有 `沐霂` 结果
- 再过滤标题里必须带 `【沐霂】`
- 再过滤掉 20 分钟以上的视频
- 最后把筛出来的视频链接按顺序送进现有下载和转写流程

只跑前 3 个视频用于试跑：

```bash
python3 scripts/autodl_run.py --limit 3
```

控制下载低音质小文件、并把长音频按 20 分钟切块做 ASR：

```bash
AUDIO_QUALITY="low" \
ASR_CHUNK_MINUTES="20" \
python3 scripts/autodl_run.py
```

如果你想更主动吃满 32GB 显存，可以切到激进档：

```bash
RESOURCE_PROFILE="aggressive" python3 scripts/autodl_run.py
```

也可以手动指定：

```bash
SEPARATOR_BATCH_SIZE="8" \
ASR_BATCH_SIZE="8" \
PUNC_BATCH_SIZE="16" \
SEPARATOR_CHUNK_SECONDS="60" \
ASR_CHUNK_MINUTES="45" \
python3 scripts/autodl_run.py
```

## 输出结构

运行完成后，主要结果在：

- `workspace/bilibili_series_2004017/subtitles/*.txt`
- `workspace/bilibili_series_2004017/subtitles/all_subtitles_merged.txt`

同时会保留中间文件，方便断点续跑：

- `workspace/bilibili_series_2004017/raw/`
- `workspace/bilibili_series_2004017/work/`
- `workspace/bilibili_series_2004017/models/`
- `workspace/bilibili_series_2004017/state/manifest.jsonl`
- `workspace/bilibili_series_2004017/state/summary.json`

`all_subtitles_merged.txt` 会按合集顺序，把每个视频的字幕自动拼成一个总文本。

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
  --input-file input.txt \
  --series-url "https://space.bilibili.com/1878154667/lists/2004017?type=series" \
  --output-root "$PWD/workspace/bilibili_series_2004017" \
  --device cuda
```

## 实现说明

- 下载：`yt-dlp`
- 输入源：优先读取根目录 `input.txt`，支持一行一个链接，空行和 `#` 注释会自动跳过
- 也支持直接读取 B 站 UP 空间搜索页，并按标题子串和最小时长过滤后自动生成待下载链接
- 人声分离：`HiDolen/Mini-BS-RoFormer-V2-46.8M`
- 语音识别：`FireRedTeam/FireRedASR2-AED`
- 辅助模块：`FireRedVAD`、`FireRedLID`、`FireRedPunc`
- FireRed 模型下载：默认 `auto`，优先尝试 ModelScope，再回退到 Hugging Face
- 下载音质：默认 `low`，优先选择低音质/小文件音频，足够做 ASR

为了适配长录播：

- 人声分离不是整段一次性推理，而是按块切分并做 overlap-add 拼接，避免长音频直接爆显存或内存
- FireRed ASR 前会把超长人声 wav 再按大块切开，逐块转写，避免几小时音频一次性读入导致内存风险

## 断点续跑

- 已下载的音频会记录在 `state/downloaded.txt`
- `input.txt` 里的重复链接会自动按规范化 URL 去重，像 `vd_source` 这种追踪参数不会导致重复下载
- 已生成的字幕 txt 默认会跳过
- 想强制重跑时加 `--overwrite`

## 参考来源

- Mini-BS-RoFormer-V2 模型卡：<https://huggingface.co/HiDolen/Mini-BS-RoFormer-V2-46.8M>
- FireRedASR2S 官方仓库：<https://github.com/FireRedTeam/FireRedASR2S>
- FireRedASR2S README 中给出的 FireRedASR2-AED / VAD / LID / Punc 下载方式
- PyTorch 官方安装页：<https://pytorch.org/get-started/locally/>
