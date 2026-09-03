# 部署指南 · App 包体信息监控台

把「App 包体信息监控台」部署到云端，实现**每天自动核验 App 在线状态 + 网站自动更新**，全程免费，约 5 分钟。

采用方案：**GitHub Actions 定时任务 + GitHub Pages 静态托管**，无需服务器、无需付费、无需域名。

---

## 一、部署前准备

- 一个 GitHub 账号（没有的话先去 github.com 注册，免费）
- 本目录下的 5 个文件，一个都不能少：

```
app-monitor/
├── index.html                  # 监控网站本体
├── apps.json                   # 在管 App 清单（单一数据源）
├── add_app.py                  # 一键添加工具
├── check_status.py             # 检测脚本（生成 data.json）
├── data.json                   # 当前核验结果
├── DEPLOY.md                   # 本文档
└── .github/
    └── workflows/
        └── update.yml          # 每日定时任务
```

> 注意：`.github` 是隐藏目录，上传时别漏掉。

---

## 二、部署步骤

### 第 1 步：创建 GitHub 仓库并上传文件

1. 登录 GitHub，点击右上角 **+** → **New repository**
2. 填写仓库信息：
   - **Repository name**：例如 `app-monitor`（建议全小写英文）
   - **Public**（Public 仓库才能免费使用 GitHub Pages；Private 使用 Pages 需付费套餐）
   - 不要勾选 "Add a README file"（避免产生冲突文件）
3. 点击 **Create repository**
4. 进入仓库后，用你习惯的方式把上面 5 个文件上传到**仓库根目录**：
   - 方式 A（推荐）：本地装好 Git 后，在 `app-monitor` 目录里执行：
     ```
     git init
     git add .
     git commit -m "init"
     git branch -M main
     git remote add origin https://github.com/你的用户名/app-monitor.git
     git push -u origin main
     ```
   - 方式 B（无 Git）：在仓库页面点 **Add file → Upload files**，把文件拖进去上传（`.github` 文件夹要单独建目录再上传 workflow 文件）

### 第 2 步：开启 GitHub Pages

1. 进入仓库 → 点击顶部 **Settings**
2. 左侧菜单找到 **Pages**（在 "Code and automation" 分组下）
3. **Build and deployment** 区域：
   - **Source** 选择 **Deploy from a branch**
   - **Branch** 选择 **main**，目录选 **/ (root)**
   - 点击 **Save**
4. 等待 1–2 分钟，页面顶部会显示网站地址，形如：
   ```
   https://你的用户名.github.io/app-monitor/
   ```
5. 用浏览器打开该地址，能看到监控台首页即部署成功。

> 提示：如果页面显示"本地预览模式"提示条，说明加载的是内置快照数据，属正常过渡状态；等第一次定时任务跑完（或手动触发一次）后即为自动模式。

### 第 3 步：验证每日自动更新（关键）

1. 进入仓库 → 点击顶部 **Actions**
2. 左侧应能看到名为 **「每日包体状态核验」** 的 workflow
3. 点进该 workflow → 右侧 **Run workflow** 下拉 → 点击绿色 **Run workflow** 按钮，手动触发一次
4. 等待约 30 秒，确认工作流图标变成绿色对勾（成功）
5. 回仓库首页看 `data.json`，提交记录里应出现一条
   `chore: 更新包体状态 2026-XX-XX` 的自动提交（由 github-actions[bot] 创建）

> 验证成功后，该 workflow 会按计划**每天北京时间 08:15 自动运行**：核验各 App → 有变化则自动更新数据并推送 → GitHub Pages 自动重新发布。全程无需人工干预。

---

## 三、日常维护

### 新增 / 移除要监控的 App

App 清单集中在 **`apps.json`**（单一数据源），两种快捷方式：

- **本地一键命令（推荐）**：在 `app-monitor` 目录执行
  ```
  python add_app.py https://apps.apple.com/us/app/xxx/id数字
  ```
  或 `python add_app.py 数字ID [地区]`。工具自动核实 → 追加 `apps.json` → 重新生成 `data.json` → 同步 `index.html` 内置快照，重复添加自动拦截。
- **部署后免本地**：在 GitHub 网页直接编辑 `apps.json` 加一行，提交后在 Actions 手动 Run 一次「每日包体状态核验」即生效。

`apps.json` 每条格式：

```json
{"name": "应用名", "storeId": "商店ID数字", "country": "us", "url": "https://apps.apple.com/us/app/xxx/id数字"}
```

- `storeId`：App Store 链接 `.../id6793454542` 里的数字部分
- `country`：地区代码（`us` 美区 / `hk` 港区等），决定从哪个商店查询
- 移除 App：删掉 `apps.json` 里对应条目即可

### 修改检测时间

编辑 `.github/workflows/update.yml` 里的 cron 表达式：

```yaml
schedule:
  - cron: '15 0 * * *'   # UTC 时间；北京时间 = UTC + 8
```

- `'15 0 * * *'` = 每天 UTC 00:15 = 北京时间 08:15
- 想改成北京时间晚上 20:00 → UTC 12:00 → `'0 12 * * *'`

### 修改网站样式 / 文案

直接编辑 `index.html` 后推送到 `main` 分支，GitHub Pages 会自动重新发布。

---

## 四、常见问题排查

| 现象 | 原因与处理 |
|---|---|
| 网站打不开 / 404 | Pages 未生效或分支配置错误。回到 Settings → Pages 核对 Source 是否为 `Deploy from a branch` + `main` + `/ (root)`；或推送后等待 1–2 分钟刷新 |
| 显示"本地预览模式" | 当前是用浏览器直接打开本地文件。部署到 GitHub Pages 后即自动模式；也可在 Actions 手动 Run 一次确认 |
| Actions 里没有 workflow | `.github/workflows/update.yml` 没上传成功（隐藏目录被漏掉），或文件名/路径不对。确认文件位于仓库根目录的 `.github/workflows/` 下 |
| 定时任务没到点执行 | GitHub Actions 的 cron 最小粒度是 5 分钟，且实际执行时间可能有 1 分钟左右的延迟，属正常现象 |
| 手动 Run 报错 | 点进 workflow 展开失败步骤看日志；最常见是 `check_status.py` 所在路径不对（应位于仓库根目录） |
| data.json 一直不更新 | 确认 6 个 App 的状态没变化（没变化时不会产生提交，属正常）；或进 Actions 看最近一次运行日志 |
| Private 仓库无法开启 Pages | GitHub Pages 免费版仅支持 Public 仓库；把仓库设为 Public，或用其他托管方案（见 README） |

---

## 五、方案原理（可选了解）

```
每天 08:15
   └─ GitHub Actions 触发「每日包体状态核验」workflow
        └─ 运行 check_status.py
             ├─ 逐个调用 App Store 官方接口 itunes.apple.com/lookup
             ├─ 判断每个 App 在线 / 离线，抓取最新包体信息
             └─ 生成 data.json（含核验时间）
        ├─ 若数据有变化 → 自动 git commit + push
        │     └─ 触发 GitHub Pages 重新构建发布 → 网站更新
        └─ 若无变化 → 跳过提交（不产生无意义提交记录）
```

网站访问时：读取 `data.json` 展示最近一次核验结果；右上角「立即检测」按钮可绕过云端数据、直接调用 App Store 接口即时刷新本次查看的在线状态。
