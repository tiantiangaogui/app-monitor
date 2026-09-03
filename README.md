# App 包体信息监控台

一个会自动更新、部署在云端的 App 包体在线状态监控页。**每小时自动核验** App Store 上各 App 的在线状态与包体信息，并把最新结果发布为网站；**发现 App 下架时自动发送邮件告警**。

## 一、这个目录里有什么

| 文件 | 作用 |
|---|---|
| `index.html` | 监控网站本体（单文件，含全部样式与逻辑） |
| `apps.json` | **在管 App 清单（单一数据源）**，新增/删除 App 主要改这里 |
| `add_app.py` | 一键添加工具：输个链接/ID 自动核实并纳入监控 |
| `check_status.py` | 检测脚本：读 `apps.json`，调用 App Store 官方接口核验每个 App，生成 `data.json`；与上一轮对比识别"新下架"并发送邮件告警（纯标准库，跨平台） |
| `data.json` | 最新一次核验结果，网站从它动态读取 |
| `.github/workflows/update.yml` | 每小时定时任务：自动运行检测脚本（含下架邮件通知）并把最新 `data.json` 推回仓库 |

网站运行机制：
- **自动模式**（部署后）：页面加载时读取 `data.json`，展示最近一次云端自动核验的结果与核验时间。
- **手动模式**：页面右上角有「立即检测」按钮，点击后通过 App Store 官方接口即时刷新全部 App 的在线状态（无需后端，仅本次查看，不写入云端数据）。
- **本地预览**：直接用浏览器打开本地 `index.html`（file://）时无法读取 `data.json`，会展示内置数据快照，并提示部署后可自动更新。

## 二、云端部署步骤（约 5 分钟，全部免费）

采用 **GitHub Actions 定时任务 + GitHub Pages 静态托管** 方案，无需服务器、无需付费。

1. **建仓库并上传**
   - 在 GitHub 新建一个仓库（Public 即可；Private 也能用 Pages 但需付费套餐，建议 Public）。
   - 将本目录下的所有文件上传到仓库根目录：
     - `index.html`、`check_status.py`、`data.json`
     - `.github/workflows/update.yml`（注意：`.github` 是隐藏目录，需确认上传成功）

2. **开启 GitHub Pages**
   - 仓库页面 → `Settings` → `Pages`
   - `Build and deployment` → `Source` 选择 **Deploy from a branch**
   - `Branch` 选 **main**，目录 `/ (root)` → Save
   - 稍等 1-2 分钟，页面会给出网站地址，形如 `https://你的用户名.github.io/仓库名/`
   - 此时网站已可访问，显示当前（初始）数据。

3. **确认自动更新已生效**
   - 仓库 → `Actions` 标签，应能看到名为「包体状态核验（每小时）」的 workflow。
   - 首次进入后可点该 workflow → 右侧 **Run workflow** 手动跑一次，验证流程正常（约 30 秒）。
   - 之后 workflow 会按计划**每小时自动运行**：核验各 App 状态 → 若 `data.json` 有变化则自动提交推送 → GitHub Pages 自动重新发布。全程无需人工干预。

4. **（推荐）配置下架邮件告警**
   - 想让"有 App 下架"时自动收到邮件（默认收件人 `tanemouse@163.com`），在仓库 `Settings → Secrets and variables → Actions` 添加 5 个密钥：`SMTP_HOST`（如 `smtp.163.com`）、`SMTP_PORT`（`465`）、`SMTP_USERNAME`（发件邮箱）、`SMTP_PASSWORD`（发件邮箱的 **SMTP 授权码**）、`MAIL_TO`（收件邮箱）。
   - 未配置时监控照常运行，只是不发邮件。详细步骤见 `DEPLOY.md` 第 4 步。

## 三、日常维护

**新增 / 移除要监控的 App**：App 清单集中在 **`apps.json`**（单一数据源），有两种快捷方式：

- **方式一（本地一键命令，推荐）**：在 `app-monitor` 目录执行
  ```
  python add_app.py <App Store 链接或 storeId>
  ```
  例如：
  ```
  python add_app.py https://apps.apple.com/us/app/xxx/id6772021868
  python add_app.py 6772021868 us
  ```
  工具会自动：核实 App 是否存在 → 追加到 `apps.json` → 重新生成 `data.json` → 同步 `index.html` 内置快照。重复添加会自动拦截。
- **方式二（已部署后、不 clone 本地）**：直接在 GitHub 仓库网页编辑 `apps.json`，加一行：
  ```json
  {"name": "应用名", "storeId": "商店ID数字", "country": "us", "url": "https://apps.apple.com/us/app/xxx/id数字"}
  ```
  提交后到 Actions 里手动 Run 一次「包体状态核验（每小时）」即可立即生效（之后每小时自动核验也会包含它）。

- `storeId`：App Store 链接 `.../id6793454542` 里的数字部分；`country` 为地区代码（`us` 美区 / `hk` 港区等）。
- 移除 App：把 `apps.json` 里对应条目删掉即可（同样本地跑 `add_app.py` 不需要，直接编辑文件）。

**修改网站样式 / 文案**：直接编辑 `index.html` 后推送到 main 分支，GitHub Pages 会自动重新发布。

**手动立即核验**：进入 Actions → 选中「包体状态核验（每小时）」→ Run workflow，即可马上跑一次检测。

## 四、常见问题

- **网站显示"本地预览模式"**：说明当前是用浏览器直接打开本地文件，`data.json` 读取不到。部署到 GitHub Pages 后即为自动模式。
- **多久更新一次**：默认每小时整点（北京时间）自动核验。想改频率，编辑 `.github/workflows/update.yml` 里的 `cron` 表达式（`0 * * * *` 为每小时整点，UTC 时间）。
- **数据没变化时会不会白跑**：不会。脚本每小时都会核验，但只有结果真的变化才提交新数据，无变化则跳过提交。
- **App 真下架了会怎样**：脚本会把该 App 标记为「离线」，网站卡片和表格会显示红色「离线」徽章，KPI 离线数随之变化；同时（若已配置 SMTP 密钥）自动发邮件到 `tanemouse@163.com` 通知包名与链接。只有"从在线变为下架"才发一次，已下架的包不会重复通知。
- **没收到下架邮件**：检查是否已配置第 4 步的 5 个 Secrets，且 `SMTP_PASSWORD` 是发件邮箱的 SMTP 授权码（非登录密码）；也可在 Actions 日志中搜索 `[邮件]` 查看发送结果。
