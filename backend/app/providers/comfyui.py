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
                    # 提取节点异常信息（完整保留 exception_message，便于上层按关键字判断降级）
                    detail = ""
                    for _, payload in status.get("messages", []):
                        if isinstance(payload, dict) and payload.get("exception_message"):
                            detail = str(payload["exception_message"]).strip()
                            break
                    raise ComfyUIError(
                        f"ComfyUI 执行出错: {detail or json.dumps(status)[:500]}"
                    )
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

    def _build_image_overrides(
        self, wf: dict, prompt: str, negative: str, count: int,
        width: int, height: int, seed: int, ref_imgs: list[Path],
    ) -> dict[str, dict]:
        """为带参考图的 IP-Adapter 工作流构建 overrides（上传图 + 注入尺寸/种子/提示词）。

        适用于任何「含若干 LoadImage 节点」的图工作流：参考图按出现顺序循环分配到各 LoadImage。
        """
        overrides: dict[str, dict] = {}
        uploaded_names = [self._upload_image(r) for r in ref_imgs]
        loadimage_nodes = [nid for nid, n in wf.items()
                           if n.get("class_type") == "LoadImage"]
        for i, nid in enumerate(loadimage_nodes):
            overrides[nid] = {"image": uploaded_names[i % len(uploaded_names)]}
        for node_id, node in wf.items():
            cls = node.get("class_type", "")
            inputs = node.setdefault("inputs", {})
            if cls == "LoadImage":
                continue
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
        return overrides

    def _generate_with_lora(
        self, template_path: str, prompt: str, negative: str, count: int,
        width: int, height: int, loras: list[tuple[str, float]],
    ) -> list[Path]:
        """SDXL + LoraLoader 路线：把角色 LoRA 注入到链式 LoraLoader 节点。

        工作流里所有 class_type==LoraLoader 的节点按 ID 升序视为一条挂载链，
        第 i 个 LoRA 填进第 i 个 LoraLoader；多余的 LoraLoader 设为 "None"（不加载）。
        """
        wf = self._load_template(template_path)
        seed = random.randint(0, 2**31)
        overrides: dict[str, dict] = {}

        # 收集 LoraLoader 节点（按数字 ID 升序，对应链式顺序）
        lora_nodes = sorted(
            (nid for nid, n in wf.items() if n.get("class_type") == "LoraLoader"),
            key=lambda x: int(x),
        )
        for idx, nid in enumerate(lora_nodes):
            if idx < len(loras):
                name, strength = loras[idx]
                overrides[nid] = {
                    "lora_name": name,
                    "strength_model": strength,
                    "strength_clip": strength,
                }
            else:
                overrides[nid] = {"lora_name": "None", "strength_model": 1.0, "strength_clip": 1.0}

        # 尺寸 / 种子 / 提示词
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
        pos = [i for i in clip_ids if "negative" not in wf[i].get("_meta", {}).get("title", "").lower()
               and "负" not in wf[i].get("_meta", {}).get("title", "")]
        neg = [i for i in clip_ids if i not in pos]
        for i in pos:
            overrides[i] = {"text": prompt}
        for i in neg:
            overrides[i] = {"text": negative}

        wf = self._inject(wf, overrides)
        logger.info("generate_images: LoRA workflow, loras=%s", [n for n, _ in loras])
        prompt_id = self._submit(wf)
        outputs = self._wait(prompt_id, settings.comfyui_image_timeout)
        images: list[Path] = []
        for node_out in outputs.values():
            for img in node_out.get("images", []):
                images.append(self._download(img, "images"))
        if not images:
            raise ComfyUIError("LoRA 工作流无图片输出，检查 SaveImage 节点是否存在")
        return images

    def generate_images(
        self, prompt: str, negative: str, count: int, width: int, height: int,
        reference_image: Path | None = None,
        reference_images: list[Path] | None = None,
        loras: list[tuple[str, float]] | None = None,
    ) -> list[Path]:
        """文生图。

        loras: [(lora文件名, 强度), ...] —— 角色一致性 LoRA，最多挂载 2 个（多角色同框）。
               提供时优先走 SDXL+LoRA 工作流，一致性远强于 IP-Adapter。
        reference_image: 单张参考图（旧 FaceID 路线，向后兼容）。
        reference_images: 多张参考图（IP-Adapter 路线，角色+场景标准照一起喂）。
        无 LoRA 时：两者都不为空走 FaceID/IP-Adapter 工作流，否则纯文生图。
        """
        # 合并参考图
        ref_imgs: list[Path] = []
        if reference_image:
            ref_imgs.append(reference_image)
        if reference_images:
            ref_imgs.extend(reference_images)

        # ---------- 优先：LoRA 路线（专业级角色一致性）----------
        lora_template = getattr(settings, "comfyui_image_lora_workflow", None)
        if loras and lora_template:
            return self._generate_with_lora(
                lora_template, prompt, negative, count, width, height, loras[:2],
            )

        # 选择工作流模板
        faceid_template = getattr(settings, "comfyui_image_faceid_workflow", None)
        use_faceid = len(ref_imgs) > 0 and bool(faceid_template)
        template_path = faceid_template if use_faceid else settings.comfyui_image_workflow
        wf = self._load_template(template_path)

        seed = random.randint(0, 2**31)
        overrides: dict[str, dict] = {}

        if use_faceid:
            # FaceID/IP-Adapter 路线：上传参考图 → 注入 LoadImage 节点 + 尺寸/种子/提示词
            overrides = self._build_image_overrides(
                wf, prompt, negative, count, width, height, seed, ref_imgs,
            )
            logger.info("generate_images: FaceID/IP-Adapter workflow, refs=%d", len(ref_imgs))
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

        try:
            prompt_id = self._submit(wf)
            outputs = self._wait(prompt_id, settings.comfyui_image_timeout)
        except ComfyUIError as exc:
            # FaceID 检测不到人脸（侧脸/远景/非人物标准照）时，降级为「仅全风格 IP-Adapter」重试，
            # 保证仍能产出与标准照服装画风一致的图，而不是整张任务失败。
            msg = str(exc)
            if use_faceid and "No face detected" in msg:
                logger.warning("generate_images: FaceID 未检测到人脸，降级为仅风格 IP-Adapter 重试")
                fallback_tpl = getattr(settings, "comfyui_image_style_workflow", None)
                if fallback_tpl:
                    wf2 = self._load_template(fallback_tpl)
                    ov2 = self._build_image_overrides(
                        wf2, prompt, negative, count, width, height, seed, ref_imgs,
                    )
                    wf2 = self._inject(wf2, ov2)
                    prompt_id = self._submit(wf2)
                    outputs = self._wait(prompt_id, settings.comfyui_image_timeout)
                else:
                    raise
            else:
                raise
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
