"""ComfyUI Provider：通过 HTTP API 驱动 AutoDL 上的 ComfyUI。

对接原理（与你今天手动操作完全一致，只是自动化）：
1. POST /prompt        提交工作流 JSON（前端 Save(API Format) 导出的模板）
   - 提交前把模板里的「提示词 / 首帧图 / 尺寸 / 种子」等字段替换成本次任务参数
2. GET  /history/{id}  轮询直到出现 outputs（生成完成）
3. GET  /view          下载产物（图片/视频），转存到平台自己的媒体目录

AutoDL 公网代理地址形如 https://uXXXX-xxxx.bjb2.seetacloud.com:8443 ，
直接作为 base_url 即可，无需 SSH 隧道。实例关机则请求失败——worker 会重试并报错，
提醒你去 AutoDL 开机。
"""
from __future__ import annotations

import json
import logging
import random
import time
import uuid
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ComfyUIError(RuntimeError):
    pass


class ComfyUIProvider:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.comfyui_base_url).rstrip("/")
        if not self.base_url or "REPLACE_ME" in self.base_url:
            raise ComfyUIError("未配置 COMFYUI_BASE_URL，请在 .env 填入 AutoDL 公网地址")
        self.client = httpx.Client(base_url=self.base_url, timeout=60.0, verify=False)

    # ---------- 底层三步 ----------
    def _upload_image(self, local_path: Path) -> str:
        """把本地图片上传到 ComfyUI input 目录，返回文件名。"""
        with open(local_path, "rb") as f:
            resp = self.client.post(
                "/upload/image",
                files={"image": (local_path.name, f, "image/png")},
                data={"type": "input", "overwrite": "true"},
            )
        resp.raise_for_status()
        return resp.json()["name"]

    def _submit(self, workflow: dict) -> str:
        resp = self.client.post("/prompt", json={"prompt": workflow})
        if resp.status_code != 200:
            raise ComfyUIError(f"提交工作流被拒: {resp.text[:500]}")
        return resp.json()["prompt_id"]

    def _wait(self, prompt_id: str, timeout: int) -> dict:
        start = time.time()
        while time.time() - start < timeout:
            resp = self.client.get(f"/history/{prompt_id}")
            history = resp.json()
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyUIError(f"ComfyUI 执行出错: {json.dumps(status)[:500]}")
                if entry.get("outputs"):
                    return entry["outputs"]
            time.sleep(settings.comfyui_poll_interval)
        raise ComfyUIError(f"等待 ComfyUI 超时（{timeout}s），检查 GPU 是否开机/显存是否不足")

    def _download(self, item: dict, subdir: str) -> Path:
        """从 /view 下载产物到平台媒体目录，返回本地路径。"""
        media_dir = Path(settings.media_root) / subdir
        media_dir.mkdir(parents=True, exist_ok=True)
        ext = item.get("type", "png")
        out = media_dir / f"{uuid.uuid4().hex[:12]}.{ext}"
        resp = self.client.get("/view", params={
            "filename": item["filename"], "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        })
        resp.raise_for_status()
        out.write_bytes(resp.content)
        return out

    # ---------- 业务封装 ----------
    def _load_template(self, path: str) -> dict:
        p = Path(path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / path
        return json.loads(p.read_text(encoding="utf-8"))

    @staticmethod
    def _inject(workflow: dict, overrides: dict[str, dict]) -> dict:
        """按节点 ID 覆盖字段值。overrides = {"3": {"text": "...", "width": 832}}"""
        for node_id, values in overrides.items():
            node = workflow.get(node_id)
            if node is None:
                logger.warning("工作流缺少节点 %s，跳过", node_id)
                continue
            inputs = node.setdefault("inputs", {})
            inputs.update(values)
        return workflow

    def generate_images(
        self, prompt: str, negative: str, count: int, width: int, height: int,
        reference_image: Path | None = None,
    ) -> list[Path]:
        """文生图。reference_image 不为空时走 FaceID 工作流（角色一致性），否则走纯文生图。"""
        # 选择工作流模板
        faceid_template = getattr(settings, "comfyui_image_faceid_workflow", None)
        use_faceid = reference_image is not None and bool(faceid_template)
        template_path = faceid_template if use_faceid else settings.comfyui_image_workflow
        wf = self._load_template(template_path)

        seed = random.randint(0, 2**31)
        overrides: dict[str, dict] = {}

        if use_faceid:
            # FaceID 路线：上传参考脸 → 注入 LoadImage 节点
            img_name = self._upload_image(reference_image)
            for node_id, node in wf.items():
                cls = node.get("class_type", "")
                inputs = node.setdefault("inputs", {})
                if cls == "LoadImage":
                    # 所有 LoadImage 都注入参考脸（FaceID 工作流里通常只有 1 个）
                    overrides[node_id] = {"image": img_name}
                elif cls in ("EmptySD3LatentImage", "EmptyLatentImage"):
                    overrides[node_id] = {"width": width, "height": height, "batch_size": count}
                elif cls in ("KSampler", "KSamplerAdvanced"):
                    overrides[node_id] = {"seed": seed}
                elif cls == "CLIPTextEncode" and "text" in inputs:
                    title = node.get("_meta", {}).get("title", "").lower()
                    if "negative" in title or "负向" in title or "负面" in title:
                        overrides[node_id] = {"text": negative}
                    else:
                        overrides[node_id] = {"text": prompt}
            logger.info("generate_images: FaceID workflow, ref=%s", img_name)
        else:
            # 纯文生图路线（Z-Image / SDXL Basic 通用）
            clip_ids = []
            for node_id, node in wf.items():
                cls = node.get("class_type", "")
                inputs = node.setdefault("inputs", {})
                if cls == "CLIPTextEncode" and "text" in inputs:
                    clip_ids.append(node_id)
                elif cls in ("EmptySD3LatentImage", "EmptyLatentImage"):
                    overrides[node_id] = {"width": width, "height": height, "batch_size": count}
                elif cls in ("KSampler", "KSamplerAdvanced"):
                    overrides[node_id] = {"seed": seed}
            pos = [i for i in clip_ids if "positive" in wf[i].get("_meta", {}).get("title", "").lower()
                   or "正向" in wf[i].get("_meta", {}).get("title", "")]
            neg = [i for i in clip_ids if "negative" in wf[i].get("_meta", {}).get("title", "").lower()
                   or "负向" in wf[i].get("_meta", {}).get("title", "") or "负面" in wf[i].get("_meta", {}).get("title", "")]
            if not pos and not neg and len(clip_ids) >= 2:
                pos, neg = [clip_ids[0]], [clip_ids[1]]
            for i in pos:
                overrides[i] = {"text": prompt}
            for i in neg:
                overrides[i] = {"text": negative}
            if len(clip_ids) == 1 and negative:
                only = clip_ids[0]
                if only not in overrides:
                    overrides[only] = {"text": prompt}

        wf = self._inject(wf, overrides)

        prompt_id = self._submit(wf)
        outputs = self._wait(prompt_id, settings.comfyui_image_timeout)
        images: list[Path] = []
        for node_out in outputs.values():
            for img in node_out.get("images", []):
                images.append(self._download(img, "images"))
        if not images:
            raise ComfyUIError("工作流无图片输出，检查 SaveImage 节点是否存在")
        return images

    def generate_video(
        self, first_frame: Path | None, motion_prompt: str, negative: str, duration: float,
        t2v: bool = False,
    ) -> Path:
        """视频生成。t2v=True 时走文生视频（纯色图占位，Sampler 结构不变）。"""
        from PIL import Image
        import tempfile

        t2v_template = getattr(settings, "comfyui_t2v_workflow", None)
        use_t2v = t2v and bool(t2v_template)
        template_path = t2v_template if use_t2v else settings.comfyui_video_workflow
        wf = self._load_template(template_path)
        seed = random.randint(0, 2**31)
        length_frames = max(17, int(duration * 16) // 4 * 4 + 1)  # Wan 16fps, 帧数需 4n+1
        overrides: dict[str, dict] = {}

        if use_t2v:
            # ---- T2V：生成纯色占位图注入 LoadImage，其他节点结构与 I2V 完全一致 ----
            logger.info("generate_video: T2V workflow, generating solid-color placeholder image")
            placeholder = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            Image.new("RGB", (624, 352), color=(128, 128, 128)).save(placeholder.name)
            placeholder.close()
            image_name = self._upload_image(Path(placeholder.name))
            for node_id, node in wf.items():
                cls = node.get("class_type", "")
                inputs = node.setdefault("inputs", {})
                if cls == "LoadImage":
                    overrides[node_id] = {"image": image_name}
                elif cls == "WanVideoImageToVideoEncode":
                    overrides[node_id] = {"num_frames": length_frames}
                elif cls == "WanVideoTextEncode":
                    overrides[node_id] = {
                        "positive_prompt": motion_prompt,
                        "negative_prompt": negative,
                    }
                elif cls == "WanVideoSampler":
                    overrides[node_id] = {"seed": seed}
        else:
            # ---- I2V：需要首帧 ----
            image_name = self._upload_image(first_frame)  # type: ignore[arg-type]
            for node_id, node in wf.items():
                cls = node.get("class_type", "")
                inputs = node.setdefault("inputs", {})
                if cls == "LoadImage":
                    overrides[node_id] = {"image": image_name}
                elif cls == "WanVideoTextEncode":
                    overrides[node_id] = {
                        "positive_prompt": motion_prompt,
                        "negative_prompt": negative,
                    }
                elif cls == "WanVideoSampler":
                    overrides[node_id] = {"seed": seed}
                elif cls == "WanVideoImageToVideoEncode":
                    overrides[node_id] = {"num_frames": length_frames}
        wf = self._inject(wf, overrides)

        prompt_id = self._submit(wf)
        outputs = self._wait(prompt_id, settings.comfyui_video_timeout)
        for node_out in outputs.values():
            # VHS_VideoCombine 与 SaveAnimatedWEBP/SaveVideo 的产物都归在 gifs/videos 下
            for vid in node_out.get("gifs", []) or node_out.get("videos", []):
                item = dict(vid)
                item.setdefault("type", "output")
                return self._download(item, "videos")
        raise ComfyUIError("工作流无视频输出，检查 Video Combine/SaveAnimatedWEBP 节点")

    def health_check(self) -> bool:
        try:
            return self.client.get("/system_stats").status_code == 200
        except Exception:
            return False
