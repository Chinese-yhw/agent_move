# ComfyUI 工作流模板导出方法（必读）

平台后端通过 ComfyUI 的 HTTP API 提交工作流，需要你把今天手动调好的工作流
导出为 **API 格式 JSON** 放到本目录：

## 步骤

1. 在 AutoDL 的 ComfyUI 界面里，把 Z-Image-Turbo 文生图工作流调到能正常出图的状态
2. （建议）给两个 CLIPTextEncode 节点双击重命名标题为 `Positive Prompt` / `Negative Prompt`
   —— 后端靠标题区分正/负向提示词；不改名则按出现顺序默认第一个为正向
3. 菜单 Workflow → **Export (API)** → 得到 json 文件
4. 保存为本目录的 `z_image_turbo_api.json`
5. 对 Wan2.1 图生视频工作流重复以上步骤，保存为 `wan21_i2v_api.json`
   - Load Image 节点保留（后端每次任务先上传首帧再填文件名）
   - 若有控制帧数/时长的节点（WanImageToVideo 的 length），后端会自动改写

## 后端注入规则（app/providers/comfyui.py）

| 节点类型 | 注入内容 |
|---|---|
| CLIPTextEncode | 正向=素材描述+画风 / 负向=质量兜底词 |
| EmptyLatentImage / EmptySD3LatentImage | width / height / batch_size(抽卡张数) |
| KSampler / KSamplerAdvanced | 随机 seed（抽卡每张不同结果） |
| LoadImage | 上传后的首帧文件名 |
| WanImageToVideo（含 length 输入） | 按镜头秒数换算帧数（16fps, 4n+1） |

## 注意

- 模板里的模型文件名必须与 AutoDL 实例中实际安装的模型一致（换机器/重装后需重新导出）
- `.env` 中 COMFYUI_BASE_URL 填 AutoDL 公网代理地址（就是今天访问 ComfyUI 用的那个 https://...:8443）
- 若走 SSH 隧道方式连接，可填 http://127.0.0.1:8188
