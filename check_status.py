# -*- coding: utf-8 -*-
"""
App 包体在线状态检测脚本
- 逐个查询 App Store 官方 iTunes Search API，判断每个 App 是否在线可下载
- 生成 data.json，供 index.html 动态加载渲染
- 与上一次结果对比，发现"新下架"的包自动发送邮件告警（SMTP 凭证从环境变量读取）
- 设计为可在 GitHub Actions 上定时运行（跨平台，仅用 Python 标准库）
"""
import json
import os
import re
import datetime
import smtplib
import urllib.request
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

# 输出始终写到脚本所在目录，保证本地与 CI 行为一致
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(BASE_DIR, "data.json")
CONFIG = os.path.join(BASE_DIR, "apps.json")
DOWN_FILE = os.path.join(BASE_DIR, "down.json")

# 收件人默认值（未配置 MAIL_TO 环境变量时使用）。
# 注意：请勿在此填写任何真实邮箱——本仓库是 Public，人人可见。
# 部署时应始终在 GitHub Secrets 里配置 MAIL_TO（会被本值优先覆盖）。
DEFAULT_MAIL_TO = ""


def load_apps():
    """从 apps.json 读取在管 App 清单（单一数据源，新增/删除 App 只需改这个文件）"""
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def fetch_lookup(store_id, country):
    """查询 iTunes lookup 接口，返回结果 dict 或 None"""
    url = "https://itunes.apple.com/lookup?id=%s&country=%s" % (store_id, country)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 status-check"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("resultCount", 0) > 0:
        return data["results"][0]
    return None


def check_app(app):
    """检查单个 App，返回标准化的包体信息 dict"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds")
    base = {
        "storeId": app["storeId"],
        "name": app["name"],
        "url": app["url"],
        "status": "unknown",
        "checkedAt": now,
        "developer": "",
        "bundleId": "",
        "releaseDate": "",
        "version": "",
        "icon": "",
    }
    try:
        r = fetch_lookup(app["storeId"], app["country"])
        if r is None:
            base["status"] = "offline"
            return base
        base["status"] = "online"
        base["name"] = r.get("trackName", app["name"])
        base["developer"] = r.get("artistName", "")
        base["bundleId"] = r.get("bundleId", "")
        base["releaseDate"] = (r.get("releaseDate") or "")[:10]
        base["version"] = r.get("version", "")
        base["url"] = (r.get("trackViewUrl", "") or app["url"]).replace("?uo=4", "")
        # 图标使用 256px 版本，更清晰
        art = r.get("artworkUrl100", "")
        if art:
            base["icon"] = art.replace("100x100bb", "256x256bb")
        return base
    except Exception:
        # 网络异常时保留未确定状态，不误判为离线
        base["status"] = "unknown"
        return base


def load_prev():
    """读取上一次核验结果 data.json（不存在时返回 None）"""
    if os.path.exists(OUTPUT):
        try:
            with open(OUTPUT, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def extract_id(url):
    """从商店链接提取 storeId：https://apps.apple.com/us/app/xxx/id6793454542 -> 6793454542"""
    m = re.search(r"/id(\d+)", url or "")
    return m.group(1) if m else None


def prev_status(prev, store_id, url):
    """在上一轮结果里查该 App 的状态；查不到返回 None"""
    if not prev:
        return None
    for p in prev.get("apps", []):
        if p.get("storeId") == store_id:
            return p.get("status")
        # 兼容旧版 data.json（无 storeId 字段）：按链接里的 id 匹配
        if extract_id(p.get("url", "")) == store_id:
            return p.get("status")
    return None


def build_mail_body(down_apps, checked_at):
    """生成下架通知邮件的正文"""
    lines = []
    lines.append("【App 包体监控台】有 App 已下架，请及时处理")
    lines.append("")
    lines.append("检测时间：" + checked_at)
    lines.append("本次共发现 %d 个 App 已下架：" % len(down_apps))
    lines.append("")
    for i, a in enumerate(down_apps, 1):
        lines.append("%d. %s" % (i, a["name"]))
        lines.append("   · Bundle ID：" + (a.get("bundleId") or "-"))
        lines.append("   · 开发者：" + (a.get("developer") or "-"))
        lines.append("   · 商店地址：" + a.get("url", ""))
        lines.append("")
    lines.append("请确认该包是被误下架还是主动下架。")
    lines.append("（此邮件由包体监控台定时自动核验触发，请勿直接回复）")
    return "\n".join(lines)


def send_mail(subject, body):
    """通过 SMTP 发送告警邮件；凭证来自环境变量，未配置则跳过（返回 False）"""
    host = os.environ.get("SMTP_HOST", "").strip()
    port_str = os.environ.get("SMTP_PORT", "465").strip()
    user = os.environ.get("SMTP_USERNAME", "").strip()
    pwd = os.environ.get("SMTP_PASSWORD", "").strip()
    to = (os.environ.get("MAIL_TO", "").strip() or DEFAULT_MAIL_TO).strip()
    if not (host and user and pwd):
        print("[邮件] 未配置 SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD，跳过邮件通知")
        return False
    if not to:
        # 未配置收件人（MAIL_TO 为空且 DEFAULT_MAIL_TO 为空），无法投递，跳过
        print("[邮件] 未配置收件人 MAIL_TO，跳过邮件通知")
        return False
    try:
        port = int(port_str)
    except ValueError:
        port = 465
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr(("App 包体监控台", user))
    msg["To"] = to
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.starttls()
        server.login(user, pwd)
        server.sendmail(user, [to], msg.as_string())
        server.quit()
        print("[邮件] 已发送下架通知 ->", to)
        return True
    except Exception as e:
        print("[邮件] 发送失败：", e)
        return False


def main():
    apps_cfg = load_apps()
    prev = load_prev()
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds")

    apps = []
    newly_down = []
    for a in apps_cfg:
        info = check_app(a)
        apps.append(info)
        # 只对"新下架"的包告警：本次 offline 且上一轮不是 offline（含无历史记录）
        if info["status"] == "offline":
            ps = prev_status(prev, a["storeId"], a["url"])
            if ps != "offline":
                newly_down.append(info)

    payload = {"checked_at": now, "apps": apps}
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    if newly_down:
        # 写入 down.json（本轮下架详情，仅留痕排查，不进 git）
        with open(DOWN_FILE, "w", encoding="utf-8") as f:
            json.dump({"detected_at": now, "down_apps": newly_down}, f, ensure_ascii=False, indent=2)
        subject = "[App 监控告警] %d 个 App 已下架" % len(newly_down)
        send_mail(subject, build_mail_body(newly_down, now))
    else:
        if os.path.exists(DOWN_FILE):
            os.remove(DOWN_FILE)

    # 输出摘要到 stdout，便于 Actions 日志查看
    online = sum(1 for a in apps if a["status"] == "online")
    print("checked_at:", payload["checked_at"])
    print("total:", len(apps), "online:", online, "offline:", sum(1 for a in apps if a["status"] == "offline"), "newly_down:", len(newly_down))
    for a in apps:
        print(" -", a["name"], "|", a["status"], "|", a["bundleId"] or "-")


if __name__ == "__main__":
    main()
