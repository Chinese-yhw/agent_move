"""FFmpeg 合成导出：镜头拼接 + 配音对齐 + 字幕烧录 + BGM。

无 moviepy 依赖，直接 subprocess 调 ffmpeg。
自动检测 imageio-ffmpeg 内置二进制（Windows 无系统 ffmpeg 时的兜底）。
items 结构见 tasks/generation.compose_episode。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from app.config import get_settings

settings = get_settings()


def _find_ffmpeg() -> tuple[str, str]:
    """返回 (ffmpeg_path, ffprobe_path)。优先 imageio-ffmpeg，其次系统 PATH。"""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            ffmpeg_bin = exe
            probe = Path(exe).with_name("ffprobe.exe" if Path(exe).suffix else "ffprobe")
            ffprobe_bin = str(probe) if probe.exists() else exe
            return ffmpeg_bin, ffprobe_bin
    except Exception:
        pass
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    return ffmpeg, ffprobe


_FFMPEG_BIN, _FFPROBE_BIN = _find_ffmpeg()


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {' '.join(cmd[:6])}... {r.stderr[-800:]}")


def export_episode(items: list[dict], bgm_path: str | None, burn_subtitle: bool) -> Path:
    """把通过审核的镜头合成为一集成片，返回输出 mp4 路径。"""
    out_dir = Path(settings.media_root) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"ep_{uuid.uuid4().hex[:10]}.mp4"

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)

        # 1) 每段：视频 + 该段配音混流（音轨缺失时补静音），统一编码参数便于 concat
        norm_files = []
        srt_events: list[tuple[float, float, str]] = []  # (start,end,text)
        cursor = 0.0
        for i, it in enumerate(items):
            seg = td_path / f"seg_{i:03d}.mp4"
            cmd = [_FFMPEG_BIN, "-y", "-i", str(it["video"])]
            for a in it["audios"]:
                cmd += ["-i", str(a)]
            n_audio = len(it["audios"])
            if n_audio:
                # 多段配音按顺序串接成一条音轨
                concat_inputs = "".join(f"[{j+1}:a]" for j in range(n_audio))
                filt = (f"{concat_inputs}concat=n={n_audio}:v=0:a=1[aout]")
                cmd += ["-filter_complex", filt, "-map", "0:v", "-map", "[aout]",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                        "-r", "16", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-ar", "24000", "-shortest", str(seg)]
            else:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-r", "16",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "24000",
                        "-t", str(it["duration"]), "-shortest", str(seg)]
            _run(cmd)
            dur = _probe_duration(seg)
            norm_files.append(seg)
            cursor += dur

            # 字幕时间轴：均分在该镜头时长内
            if burn_subtitle and it["subtitles"]:
                per = dur / len(it["subtitles"])
                for k, (text, _) in enumerate(it["subtitles"]):
                    srt_events.append((
                        cursor - dur + k * per,
                        cursor - dur + (k + 1) * per,
                        text,
                    ))

        # 2) concat 拼接
        list_file = td_path / "list.txt"
        list_file.write_text(
            "\n".join(f"file '{f.as_posix()}'" for f in norm_files), encoding="utf-8"
        )
        merged = td_path / "merged.mp4"
        _run([_FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
              "-c", "copy", str(merged)])

        # 3) 字幕 + BGM
        final_inputs = [_FFMPEG_BIN, "-y", "-i", str(merged)]
        filters = []
        chain = "[0:v]"
        if burn_subtitle and srt_events:
            srt = td_path / "subs.srt"
            srt.write_text(_make_srt(srt_events), encoding="utf-8")
            filters.append(f"{chain}subtitles='{srt.as_posix()}'[vout]")
            chain = "[vout]"
        if bgm_path:
            final_inputs += ["-stream_loop", "-1", "-i", bgm_path]
            filters.append("[0:a][1:a]amix=inputs=2:duration=first:weights=1 0.25[aout]")
            audio_map = ["-map", "[aout]"]
        else:
            audio_map = ["-map", "0:a"]
        if filters:
            final_inputs += ["-filter_complex", ";".join(filters),
                             "-map", chain.replace("[", "").replace("]", ""), *audio_map]
            _run([*final_inputs, "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                  "-c:a", "aac", str(out)])
        else:
            out.write_bytes(merged.read_bytes())

    return out


def _probe_duration(p: Path) -> float:
    r = subprocess.run(
        [_FFPROBE_BIN, "-v", "quiet", "-print_format", "json", "-show_format", str(p)],
        capture_output=True, text=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _make_srt(events: list[tuple[float, float, str]]) -> str:
    def ts(sec: float) -> str:
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02}:{int(m):02}:{int(s):02},{int((s % 1) * 1000):03d}"

    lines = []
    for i, (a, b, text) in enumerate(events, 1):
        lines += [str(i), f"{ts(a)} --> {ts(b)}", text, ""]
    return "\n".join(lines)
