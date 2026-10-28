# App 包体信息监控台

一个部署在 GitHub Pages 上的双平台 App 包体监控墙。页面顶部可切换 **iOS / Android**：iOS 走 App Store 官方接口，约每 4 小时核验一次；Android 走 Google Play 抓取，每天核验一次。包体下架时自动发邮件告警。**不需要服务器，也不需要数据库。**

线上地址：`https://tiantiangaogui.github.io/app-monitor/`

## 一、监控概览

| | iOS | Android |
|---|---|---|
| 数据来源 | iTunes Lookup 官方接口 | Google Play 商品页（`google-play-scraper`） |
| 配置清单 | `apps.json` | `android_apps.json` |
| 采集脚本 | `check_status.py` | `check_android.py` |
| 定时任务 | `.github/workflows/update.yml` | `.github/workflows/update_android.yml` |
| 触发频率 | 每小时尝试，脚本内 4 小时节流 | 每天 10:00 一次，脚本内 20 小时节流 |
| 结果数据 | `data.json` | `data_android.json` |
| 下架快照 | `meta.json` | `meta_android.json` |
| 页面手动刷新 | 支持「立即检测」 | 不支持（Google Play 有 CORS 限制） |
| 告警邮件 | 独立邮件 | 独立邮件 |

两条链路完全独立：Android 抓取失败、Google 改版、邮件配置异常，都不会阻塞 iOS 的核验与提交，反之亦然。

## 二、文件说明

| 文件 | 作用 |
|---|---|
| `index.html` | 监控网站本体，单文件包含全部样式与逻辑，无外部依赖 |
| `apps.json` | iOS 在管 App 清单：`name` / `storeId` / `country` / `url` |
| `check_status.py` | iOS 采集：查 iTunes Lookup，生成 `data.json`，比对上一轮识别「新下架」并发信（纯标准库） |
| `data.json` | iOS 最新核验结果，页面直接读取 |
| `meta.json` | iOS 元数据快照，包下架后用于兜底展示图标/开发者/Bundle ID/类型/版本/上架日期 |
| `android_apps.json` | Android 在管包清单：`name` / `packageName` / `country` / `lang` / `url` |
| `check_android.py` | Android 采集：查 Google Play，生成 `data_android.json`，带独立快照与告警 |
| `data_android.json` | Android 最新核验结果，页面切到 Android 页签时读取 |
| `meta_android.json` | Android 元数据快照，含更新日期/下载量/评分，下架后兜底展示 |
| `add_app.py` | iOS 一键加包工具（Android 暂不支持，直接编辑 `android_apps.json`） |
| `.github/workflows/update.yml` | iOS 定时任务：核验 → 有变化才提交 → Pages 自动重新发布 |
| `.github/workflows/update_android.yml` | Android 每日定时任务，与 iOS 完全独立 |
| `DEPLOY.md` | 更详细的部署与 Secrets 配置步骤 |

运行期还会产生 `down.json` / `down_android.json`（下架留痕）和 `.env`（本地邮件自检），都写在 `.gitignore` 里，不会进入仓库。

## 三、运行机制

**自动模式**：页面加载时读取 `data.json` 与 `data_android.json`（`cache: no-store`，不吃浏览器缓存），展示最近一次云端核验的结果和时间戳。两个文件各自独立，哪个先更新就显示哪个的时间。

**iOS 手动模式**：右上角「立即检测」按钮，通过 JSONP 直连 iTunes 官方接口即时刷新，仅影响当前页面，不写回云端数据。Android 页签下该按钮自动隐藏。

**下架兜底**：包下架后官方接口不再返回任何字段，页面改为从 `meta.json` / `meta_android.json` 读取最后一次在线时的快照，并在卡片下方标注「已下架，以下信息为最后一次在线（时间）的存档快照」。

**本地预览**：直接用浏览器打开 `index.html`（`file://`）读不到数据文件，会回退到内置的 `FALLBACK_APPS` / `FALLBACK_ANDROID` 快照，并提示当前是本地预览模式。

## 四、部署步骤

1. **建仓库并上传全部文件**
   建议 Public（Private 用 Pages 需付费套餐）。除 `index.html`、两个采集脚本、两个配置文件外，**注意把 `.github` 目录一起上传**（隐藏目录，容易漏），否则定时任务不会生效。

2. **开启 GitHub Pages**
   `Settings → Pages` → Source 选 **Deploy from a branch** → Branch 选 **main**、目录 `/ (root)` → Save。1~2 分钟后得到站点地址。

3. **确认两个定时任务都在**
   `Actions` 标签下应能看到「包体状态核验」与「Android 包体状态核验（每日）」，各手动 Run 一次验证链路。首次运行后 `data.json` / `data_android.json` 会被写入并自动提交。

4. **（推荐）配置下架邮件告警**
   在 `Settings → Secrets and variables → Actions` 添加 5 个密钥，iOS 与 Android 共用同一套：

   | Secret | 说明 |
   |---|---|
   | `SMTP_HOST` | 如 `smtp.gmail.com` |
   | `SMTP_PORT` | 如 `465` |
   | `SMTP_USERNAME` | 发件邮箱 |
   | `SMTP_PASSWORD` | 邮箱的 **SMTP 授权码/应用专用密码**（不是登录密码） |
   | `MAIL_TO` | 收件邮箱 |

   未配置时监控照常运行，只是不发邮件。详见 `DEPLOY.md` 第 4 步。

## 五、日常维护

### 新增 iOS 包

清单是单一数据源 `apps.json`，两种方式：

- **本地一键**（推荐）：
  ```
  python add_app.py https://apps.apple.com/us/app/xxx/id6772021868
  python add_app.py 6772021868 us
  ```
  工具会核实包是否存在 → 追加清单 → 重新生成 `data.json` → 同步 `index.html` 内置快照，重复添加会被拦截。
- **网页直接改**：在 GitHub 上编辑 `apps.json`，追加一条：
  ```json
  {"name": "应用名", "storeId": "商店ID数字", "country": "us", "url": "https://apps.apple.com/us/app/xxx/id数字"}
  ```

`storeId` 是链接里 `.../id6793454542` 的数字部分；`country` 是地区代码（`us` / `hk` / `ph` 等）。**地区必须填对** —— 只在特定区上架的包，用错地区会查不到而被误判为下架。

### 新增 Android 包

编辑 `android_apps.json`，追加一条：

```json
{
  "name": "应用名",
  "packageName": "com.example.app",
  "country": "us",
  "lang": "en",
  "url": "https://play.google.com/store/apps/details?id=com.example.app"
}
```

`packageName` **区分大小写**（如 `com.PokaLive`），必须和 Play 链接里 `id=` 后面的字符串完全一致。改完推送到 main，到 Actions 手动 Run 一次 Android 任务（勾选 `force` 可跳过 20 小时节流）。

### 其他

- **改样式/文案**：编辑 `index.html` 推送到 main，Pages 自动重新发布。
- **删除包**：从对应 json 里删掉条目即可，无需其他操作。
- **手动核验**：Actions → 选中对应 workflow → Run workflow；iOS/Android 都支持 `force` 入参，用于跳过节流立即执行。

## 六、字段口径

| 页面字段 | iOS 来源 | Android 来源 |
|---|---|---|
| 包标识 | `bundleId` | `packageName` |
| 名称 / 开发者 | `trackName` / `artistName` | `title` / `developer` |
| 主类型 | `primaryGenreName` | `genre` |
| 上架日期 | `releaseDate` | `released` |
| 当前版本 | `version` | `version` |
| 在线状态 | `resultCount` | 查询是否 404 |
| 更新日期 | — | `updated` |
| 下载量 | — | `installs` |
| 评分 | — | `score` / `ratings` |

三个容易误解的地方：

- **下载量是分档标签，不是精确值。** Google 返回的是 `10,000+`、`100,000+` 这样的区间。真实下载量从 12 万涨到 18 万，字段仍是 `100,000+`，跨档才会变。
- **评分保留一位小数。** 原始值形如 `3.1578948`，统一四舍五入到一位，小幅波动不会体现在页面上。
- **日期按 UTC 截取。** iOS 的 `releaseDate` 是 UTC 时间戳，脚本取前 10 位，因此 UTC 凌晨上架的包，显示的日期可能与北京时间差一天。

## 七、常见问题

- **多久更新一次**：iOS 约每 4 小时，Android 每天一次（北京时间 10:00 触发）。页面顶部的时间戳就是数据截止时间。
- **为什么定时任务不是整点跑**：GitHub 的 `schedule` 不保证准点，免费仓库高峰会延迟甚至跳过。因此 iOS 改成**每小时触发 + 脚本内 4 小时节流**，用更多触发机会换取稳定的实际间隔；Android 用每天触发 + 20 小时节流留出延迟容错。
- **数据没变化会不会空提交**：不会。工作流里有 `git diff --cached --quiet` 判断，无变化直接跳过提交。
- **怎么防止误报下架**：iOS 查询失败会重试 3 次；Android 要连续 3 次确认 404 才判定离线，期间只要出现网络异常就标记「未确认」（黄色徽章），绝不因一次抖动发告警邮件。
- **下架后会重复发邮件吗**：不会。只对「从在线变为下架」的首轮发送，已下架的包不会重复通知。
- **没收到下架邮件**：检查 5 个 Secrets 是否齐全，`SMTP_PASSWORD` 必须是授权码而非登录密码；可在 Actions 日志里搜 `[邮件]` 看发送结果。
- **页面显示「本地预览模式」**：说明读不到数据文件，通常是直接用 `file://` 打开了本地 HTML，部署到 Pages 后即为自动模式。
