# boss- / pet_boss

像素风 **AI 办公室** 求职助手：简历解析与用户画像、多 Agent 协同搜岗与分析，主界面是可视化宠物页。

仓库：[yangxinyi724-ship-it/boss-](https://github.com/yangxinyi724-ship-it/boss-)

---

## 能做什么

| 能力 | 说明 |
|------|------|
| **AI 办公室（主界面）** | 像素场景 + 多工位 AI，浏览器打开即可操作 |
| **秘书 AI** | 上传简历、解析画像、日报 / 精选、邮箱配置 |
| **侦察 AI** | 按城市三级地区与硬性条件搜岗，自动关键词，列表扫完再换词 |
| **分析 AI** | 对候选岗打分，通过分可调，通过岗进入右侧岗位栏 |
| **监控 AI** | 监测搜岗流、浏览器卡死时可重启自动化窗口 |
| **工作时间表** | 按配置时段自动开搜 / 下班暂停 |
| **CLI** | 登录、状态、城市等命令行能力，可与 Web 共用本地登录态 |

数据默认保存在 `~/.boss-agent/`（登录态加密存储）。

---

## 环境要求

- Python **3.10+**
- Windows / macOS / Linux
- 使用浏览器自动化搜岗时需安装 Chromium（见下方）

---

## 安装

```bash
# 克隆
git clone https://github.com/yangxinyi724-ship-it/boss-.git
cd boss-

# 推荐：可编辑安装（含 Web 依赖）
pip install -e ".[web]"

# 开发 / 跑测试另加
pip install -e ".[web,dev]"
```

首次用浏览器通道前，安装 patchright 的 Chromium：

```bash
python -m patchright install chromium
```

---

## 快速开始（推荐：Web 办公室）

```bash
boss web
# 或
boss profile web
```

浏览器打开提示的地址（一般为 `http://127.0.0.1:8765`），默认进入 **`/pet` 宠物页**。

建议上手顺序：

1. **监控 AI 工位**：登录 BOSS / 从本机浏览器同步 Cookie  
2. **秘书 AI 工位**：上传简历并解析画像  
3. **侦察 AI 工位**：选省 → 市（→ 区），保存筛选条件  
4. 顶部栏：**开始搜岗**（或等工作时段自动启动）  
5. 右侧栏查看 **分析通过** 的岗位，收藏或拒绝  

改完 `pet.js` / `pet.css` 后刷新即可（`/pet` 会按文件修改时间自动带 `?v=`）。

---

## 办公室工位一览

| 工位 | 职责 |
|------|------|
| 侦察 AI（ZC） | 城市 / 筛选 / 清空侦察历史 |
| 分析 AI（FX） | 通过分、职业阶段等分析设置 |
| 监控 AI（JK） | BOSS 登录、Token、运行监控 |
| 秘书 AI（MS） | 简历、邮箱、日报相关 |
| 资料柜 | 档案、日报精选等 |

工作时段默认（可在 `src/pet_boss/web/static/pet/desks.json` 调整）：

- 09:00–12:00  
- 13:00–17:00  
- 18:00–21:00  

---

## 常用 CLI

```bash
boss --help
boss login          # 登录（Cookie / CDP / 扫码等降级）
boss status         # 登录与环境状态
boss cities         # 城市列表
boss doctor         # 环境自检
boss web            # 启动 Web 办公室
```

全局选项示例：

```bash
boss --data-dir ~/.boss-agent --log-level info web
```

---

## 项目结构（简要）

```
src/pet_boss/
  web/           # Starlette 服务 + 宠物页 static（pet.html/js/css）
  agents/        # 侦察 / 分析 / 监控 / 秘书管道
  api/           # BOSS API 与浏览器会话
  auth/          # 登录态
  profile/       # 用户画像
  secretary/     # 秘书配置与报告
  commands/      # CLI 子命令
tests/           # pytest
```

面向用户的新功能与 UI 改动，请优先改宠物页：

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

本工具通过用户本人登录态访问 BOSS 直聘，用于个人求职辅助。请遵守平台用户协议与当地法规，勿用于批量骚扰、撞库或绕过风控。自动化可能触发平台风控，请合理设置节奏与工作时段。

---

## 许可证

MIT License — 见 [LICENSE](./LICENSE)。
