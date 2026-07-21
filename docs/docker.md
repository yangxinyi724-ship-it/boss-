# Docker 使用教程

克隆仓库 → 安装 Docker → 启动。

## 1. 安装 Docker

| 系统 | 下载 |
|------|------|
| Windows | [Docker Desktop](https://www.docker.com/products/docker-desktop/)（建议启用 WSL 2） |
| macOS | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
| Linux | 发行版 Docker Engine + Compose 插件，或 Desktop |

安装后打开 Docker，确认终端可用：

```bash
docker version
docker compose version
```

Windows 若提示找不到 `docker`：确认 Desktop 已启动，并**新开**一个终端再试。

## 2. 获取代码并启动

```bash
git clone https://github.com/yangxinyi724-ship-it/boss-.git
cd boss-

# 可选：改端口等（不要提交 .env）
cp .env.example .env

docker compose up -d --build
```

首次构建会下载基础镜像、安装依赖并装 Chromium，可能较久。完成后浏览器打开：

**http://127.0.0.1:8787**

（若改了 `BOSS_PORT`，用对应端口。）

## 3. 上手（容器内）

与本地 `boss web` 相同界面，默认进 `/pet`：

1. **监控 AI**：登录 BOSS（见下一节）
2. **秘书 AI**：上传简历、解析画像
3. **侦察 AI**：选城市与筛选条件
4. 顶部栏开始搜岗；右侧栏看分析通过岗位

常用命令：

```bash
docker compose logs -f boss   # 日志
docker compose ps             # 状态
docker compose restart boss   # 重启
docker compose down           # 停止（不删数据卷）
```

## 4. 登录说明（重要）

容器与宿主机隔离，因此：

| 方式 | 容器里 |
|------|--------|
| 本机 Chrome Cookie 同步 | 不可用 |
| CDP 连本机浏览器 | 不可用 |
| 监控 AI 扫码 / 粘贴 Token·Cookie | **可用（推荐）** |

请在宠物页 → **监控 AI（JK）** 完成登录。

## 5. 数据与多人使用

- 登录态、画像、数据库等在 Docker 卷 **`boss-data`**（容器内 `/data`）
- **每个人/每台电脑** 各自有自己的卷，互不影响
- `docker compose down` **不会**删卷；要清空数据才用：

```bash
docker compose down -v
```

加密登录态时，程序会把机器标识写到卷内 `auth/machine.id`。因此：

- **同一台机器上重建容器**：一般不用改任何密钥，登录态仍可用
- **不要把别人的数据卷或 `.env` 里的密钥提交/分享出去**

### 可选：`.env`

```bash
cp .env.example .env
```

可改端口、时区。`BOSS_AGENT_MACHINE_ID` **默认留空**。仅当你要把整个数据卷拷到另一台机器、且希望不解绑登录态时，才在两边 `.env` 设成同一个自拟长字符串（仅你自己知道）。

## 6. 常见问题

**端口被占用**  
改 `.env` 里 `BOSS_PORT=8788`，再 `docker compose up -d`。

**页面打不开**  
`docker compose ps` 看是否 Up；`docker compose logs boss` 查报错；确认 Desktop 在跑。

**重建后提示登录失效**  
先确认没用 `down -v` 删卷。若整卷换机，见上一节可选 `BOSS_AGENT_MACHINE_ID`，或重新在监控 AI 登录即可。

**只要 Web、不需要 Docker**  

```bash
pip install -e ".[web]"
python -m patchright install chromium
boss web
```

## 7. 文件说明

| 文件 | 作用 |
|------|------|
| `Dockerfile` | 构建含 Web + Chromium 的镜像 |
| `docker-compose.yml` | 端口、数据卷、环境变量 |
| `.env.example` | 本机配置模板（复制为 `.env`） |
| `.dockerignore` | 减小构建上下文 |
