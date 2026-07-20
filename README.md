# boss- · AI 办公室求职助手

本地运行的 **多 Agent 求职工作台**：像素风办公室界面 + 侦察 / 分析 / 监控 / 秘书协同，持续搜岗、筛岗、沉淀结果。

| | |
|---|---|
| **仓库** | [yangxinyi724-ship-it/boss-](https://github.com/yangxinyi724-ship-it/boss-) |
| **包名** | PyPI / 工程名 `boss-agent-cli` · Python 包 `pet_boss` · CLI `boss` |
| **主界面** | `boss web` → `/pet` 宠物页 |
| **数据目录** | `~/.boss-agent/`（登录态本地加密存储） |

---

## 演示

> 当前成片约 428×240。要清晰请用 **1280×720 以上** 重录，覆盖 `docs/media/*.mp4`。

### 登录

<video src="docs/media/demo-login.mp4" controls width="100%" muted playsinline></video>

### 上传简历

<video src="docs/media/demo-resume.mp4" controls width="100%" muted playsinline></video>

### 搜岗

<video src="docs/media/demo-scout.mp4" controls width="100%" muted playsinline></video>

### RAG

<video src="docs/media/demo-reject.mp4" controls width="100%" muted playsinline></video>

---

## 项目概览

面向个人求职场景的本地工具：后端持有搜岗生命周期，前端订阅事件流；刷新页面不会打断正在跑的任务。

**能力一览**

| 模块 | 做什么 |
|------|--------|
| **AI 办公室** | 像素场景多工位；浏览器打开即可操作 |
| **侦察 AI** | 省 → 市 → 区；硬性筛选；列表扫完再换词 |
| **分析 AI** | 对候选岗打分；通过分可调；结果进岗位栏与资料柜 |
| **监控 AI** | BOSS 登录 / Token；浏览器异常时可重启自动化窗口 |
| **秘书 AI** | 简历解析、画像、日报 / 精选、邮箱 |
| **工作时间表** | 按时段自动开搜 / 下班暂停 |
| **CLI** | 登录、状态、城市、自检等，与 Web 共用登录态 |


## 环境要求

- Python **3.10+**
- Windows / macOS / Linux
- 使用浏览器通道搜岗时需安装 Chromium（见下）

---

## 安装

```bash
git clone https://github.com/yangxinyi724-ship-it/boss-.git
cd boss-

# 推荐：可编辑安装（含 Web）
pip install -e ".[web]"

# 开发 / 跑测试
pip install -e ".[web,dev]"
```

首次使用浏览器自动化前：

```bash
python -m patchright install chromium
```

---

## 快速开始

```bash
boss web
# 或
boss profile web
```

浏览器打开提示地址（一般为 `http://127.0.0.1:8765`），默认进入 **`/pet`**。

**建议上手顺序**

1. **监控 AI**：登录 BOSS，或从本机浏览器同步 Cookie  
2. **秘书 AI**：上传简历并解析画像  
3. **侦察 AI**：选省 → 市（→ 区），保存筛选条件  
4. 顶部栏：**开始搜岗**（或等待工作时段自动启动）  
5. 右侧栏查看 **分析通过** 的岗位；资料柜可回看历史通过 / 精选 / 候选池  

改完 `pet.js` / `pet.css` 后刷新即可（`/pet` 按文件 mtime 自动带 `?v=`）。

---

## 办公室工位

| 工位 | 入口职责 |
|------|----------|
| 侦察 AI（ZC） | 城市 / 筛选 / 清空侦察历史 |
| 分析 AI（FX） | 通过分等分析设置 |
| 监控 AI（JK） | BOSS 登录、Token、运行监控 |
| 秘书 AI（MS） | 简历、邮箱、日报 |
| 资料柜 | 档案、每日精选、分析通过历史、候选池等 |
| 右侧岗位栏 | 本轮分析通过岗位；收藏 / 拒绝 |

默认工作时段（可在 `src/pet_boss/web/static/pet/desks.json` 调整）：

- 09:00–12:00  
- 13:00–17:00  
- 18:00–21:00  

---

## 常用 CLI

```bash
boss --help
boss login          # 登录（Cookie / CDP / 扫码等）
boss status         # 登录与环境状态
boss cities         # 城市列表
boss doctor         # 环境自检
boss web            # 启动 Web 办公室
```

```bash
boss --data-dir ~/.boss-agent --log-level info web
```

---

## 项目结构

```
src/pet_boss/
  web/           # Starlette 服务 + 宠物页 static
  agents/        # 侦察 / 分析 / 监控 / 秘书管道
  api/           # BOSS API 与浏览器会话
  auth/          # 登录态
  profile/       # 用户画像
  secretary/     # 秘书配置与报告
  commands/      # CLI 子命令
tests/           # pytest
docs/media/      # README 演示动图（自备 GIF）
```

面向用户的新功能与 UI，优先改宠物页：

- `src/pet_boss/web/static/pet.html`
- `src/pet_boss/web/static/pet.js`
- `src/pet_boss/web/static/pet.css`
- `src/pet_boss/web/static/pet/desks.json`

---

## 测试

```bash
pytest -q
```

---

## 合规说明

本工具通过**用户本人登录态**访问 BOSS 直聘，用于个人求职辅助。请遵守平台用户协议与当地法规，勿用于批量骚扰、撞库或绕过风控。自动化可能触发平台风控，请合理设置节奏与工作时段。

---

## 许可证

MIT License — 见 [LICENSE](./LICENSE)。
