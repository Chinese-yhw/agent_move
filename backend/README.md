# 短剧生成平台 · 后端

FastAPI + SQLAlchemy 2.0 + Celery + ComfyUI(AutoDL) + DeepSeek + CosyVoice。

## 本地快速启动（Windows，无需 Docker）

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e .

copy .env.example .env
# 编辑 .env：
#   COMFYUI_BASE_URL = AutoDL 公网地址（今天访问 ComfyUI 用的 https://...:8443）
#   LLM_API_KEY      = DeepSeek key
# DATABASE_URL 不填则默认 SQLite，起步零依赖

# 按 workflows/README.md 导出两个 API 格式工作流覆盖占位文件

# 终端1：API
uvicorn app.main:app --reload --port 8000

# 终端2：worker（开发期无 Redis 时任务会同步执行，可先跳过）
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=1
```

打开 http://localhost:8000/docs 即可用 Swagger 调全部接口。

## 核心接口一览

| 阶段 | 接口 |
|---|---|
| 项目/剧本 | `POST /api/projects`、`POST /api/projects/{id}/scripts` |
| 分镜导入 | `POST /api/scripts/{id}/shots` |
| 内容检测 | `POST /api/scripts/{id}/detect` → task.result.issues |
| 素材提取 | `POST /api/scripts/{id}/extract` → assets 表 |
| 标准照抽卡 | `POST /api/assets/{id}/images` → `GET candidates` → `POST select`(锁定) |
| 镜头视频抽卡 | `POST /api/shots/{id}/videos` → `GET candidates` → `POST approve` |
| 配音 | `POST /api/scripts/{id}/tts` |
| 合成导出 | `POST /api/compose/export` → task.result.video_url |
| 成本看板 | `GET /api/projects/{id}/costs` |

## ¥500/100集 成本控制如何落地

1. **单 GPU worker 串行**（compose 里 `--concurrency=1` + `prefetch=1`）：机器利用率拉满，不空转计费
2. **标准照全季一次生成 + 锁定复用**：asset.status=已锁定 后所有镜头强制引用该图
3. **抽卡次数即预算**：`n_candidates` 参数控制；默认图像 4 张、视频 2 条
4. **每任务记录实际 GPU 秒数 × 时租**（tasks.cost_yuan），`/costs` 接口实时汇总——超预算立刻可见
5. **用完关机**：AutoDL 实例不跑任务时手动/脚本关机；平台 health 接口会提示 comfyui_reachable=false

## 生产迁移

```bash
alembic init migrations   # 首次
# DATABASE_URL 换成 postgresql+asyncpg://...
```
