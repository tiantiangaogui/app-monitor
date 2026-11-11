# -*- coding: utf-8 -*-
"""
Android 包体在线状态检测脚本（独立于 iOS 巡检链路）
- 逐个查询 Google Play 商店页，判断每个包是否在线可下载
- 生成 data_android.json，供 index.html 的 Android 页签渲染
- 与上一轮结果对比，发现"新下架"时发送独立的告警邮件
- 每天核验一次（由 update_android.yml 触发），与 iOS 的每4小时巡检互不影响
"""
import datetime
import json
import os
import re
import smtplib
import sys
import time
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

try:
    from google_play_scraper import app as gp_app
    from google_play_scraper.exceptions import NotFoundError
except ImportError:
    print("[错误] 缺少依赖 google-play-scraper，请先执行：pip install google-play-scraper==1.2.7")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(BASE_DIR, "data_android.json")
CONFIG = os.path.join(BASE_DIR, "android_apps.json")
META_FILE = os.path.join(BASE_DIR, "meta_android.json")
DOWN_FILE = os.path.join(BASE_DIR, "down_android.json")
INDEX_HTML = os.path.join(BASE_DIR, "index.html")

# 写入 index.html 内置快照的字段顺序（与页面渲染所需字段一致）
FALLBACK_KEYS = ("packageName", "bundleId", "name", "developer", "genre", "releaseDate",
                 "version", "updatedDate", "installs", "score", "ratings", "url", "icon", "status")
# 无法实时取数时，从"最后一次在线"的存档里回填的字段
SNAPSHOT_FIELDS = ("developer", "genre", "releaseDate", "version", "icon",
                   "updatedDate", "installs", "ratings", "contentRating")

DEFAULT_MAIL_TO = ""


def mask_mail(addr):
    """日志只保留首字符与域名，避免 Actions 日志（公开可查）暴露完整收件地址"""
    if "@" not in addr:
        return "***"
    local, domain = addr.split("@", 1)
    return f"{local[:1]}***@{domain}"


def load_apps():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def now_cst():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def read_output():
    """读取上一轮结果；文件缺失、损坏或结构不对时一律返回 None。"""
    if not os.path.exists(OUTPUT):
        return None
    try:
        with open(OUTPUT, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d.get("apps"), list) else None
    except Exception:
        return None


def throttled():
    """距上次核验不足 MIN_INTERVAL_HOURS 小时则跳过（Android 默认 24 小时）"""
    if os.environ.get("FORCE_CHECK", "").strip().lower() in ("1", "true", "yes"):
        return None
    try:
        interval = float(os.environ.get("MIN_INTERVAL_HOURS", "24"))
    except ValueError:
        interval = 24.0
    if interval <= 0:
        return None
    raw = (read_output() or {}).get("checked_at")
    if not raw:
        return None
    try:
        last = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    elapsed = (now_cst() - last).total_seconds() / 3600.0
    if elapsed < interval:
        return "距上次核验仅 %.2f 小时（阈值 %.2f 小时），本轮跳过" % (elapsed, interval)
    return None


def load_meta():
    if os.path.exists(META_FILE):
        try:
            with open(META_FILE, encoding="utf-8") as f:
                m = json.load(f)
            if isinstance(m.get("apps"), dict):
                return m
        except Exception:
            pass
    return {"_note": "Android 元数据快照库：记录每个包最后一次在线时的名称/开发者/包名/类型/上架日期/版本，供下架后兜底展示。", "apps": {}}


def save_meta(meta):
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def upsert_meta(meta, info):
    store = meta.setdefault("apps", {})
    store[info["packageName"]] = {
        "name": info["name"],
        "developer": info["developer"],
        "packageName": info["packageName"],
        "genre": info["genre"],
        "releaseDate": info["releaseDate"],
        "version": info["version"],
        "icon": info["icon"],
        "updatedDate": info.get("updatedDate", ""),
        "installs": info.get("installs", ""),
        "score": info.get("score"),
        "ratings": info.get("ratings"),
        "contentRating": info.get("contentRating", ""),
        "updatedAt": info["checkedAt"],
    }


def to_iso_date(text):
    """Google Play 的 released 字段形如 'Jul 25, 2021'，统一转成 2021-07-25"""
    if not text:
        return ""
    for fmt in ("%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


def to_iso_from_ts(ts):
    """Play 的 updated 是 Unix 秒，按 UTC 日期输出，与 iOS 口径保持一致"""
    try:
        return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return ""


def fetch_play(package, country, lang, attempts=3, delay=5):
    """
    查询 Google Play。
    - 3 次全部 NotFoundError：确认下架，返回 None
    - 有网络/限流异常且未全部 404：抛异常，由调用方标记 unknown（绝不误判下架）
    """
    not_found = 0
    last_error = None
    for i in range(attempts):
        try:
            return gp_app(package, lang=lang, country=country)
        except NotFoundError:
            not_found += 1
        except Exception as e:
            last_error = e
        if i < attempts - 1:
            time.sleep(delay)
    if not_found == attempts:
        return None
    raise last_error or RuntimeError("Google Play 查询失败")


def fill_from_snapshot(base, meta, pkg):
    """下架或网络未确认时，用最后一次在线的存档回填展示字段，避免页面空白。"""
    snap = (meta.get("apps") or {}).get(pkg)
    if not snap:
        return base
    for k in SNAPSHOT_FIELDS:
        base[k] = snap.get(k, "")
    score = snap.get("score")
    base["score"] = round(score, 1) if isinstance(score, (int, float)) else None
    base["infoSnapshot"] = True
    base["snapshotAt"] = snap.get("updatedAt", "")
    return base


def check_app(app, meta):
    pkg = app["packageName"]
    base = {
        "storeId": pkg,
        "packageName": pkg,
        "bundleId": pkg,
        "name": app.get("name") or pkg,
        "url": app.get("url") or "https://play.google.com/store/apps/details?id=" + pkg,
        "status": "unknown",
        "checkedAt": now_cst().isoformat(timespec="seconds"),
        "developer": "",
        "genre": "",
        "releaseDate": "",
        "version": "",
        "icon": "",
        "updatedDate": "",
        "installs": "",
        "score": None,
        "ratings": None,
        "contentRating": "",
        "infoSnapshot": False,
        "snapshotAt": "",
    }

    # 只有 fetch_play 会抛异常：网络失败 → 未确认，绝不误判下架
    try:
        r = fetch_play(pkg, app.get("country", "us"), app.get("lang", "en"))
    except Exception as e:
        print("[未确认] %s 查询失败：%s: %s" % (pkg, type(e).__name__, e))
        return fill_from_snapshot(base, meta, pkg)

    if r is None:
        base["status"] = "offline"
        return fill_from_snapshot(base, meta, pkg)

    base.update({
        "status": "online",
        "name": r.get("title") or base["name"],
        "developer": r.get("developer", ""),
        "genre": r.get("genre", ""),
        "releaseDate": to_iso_date(r.get("released", "")),
        "version": r.get("version", ""),
        "icon": r.get("icon", ""),
        "updatedDate": to_iso_from_ts(r.get("updated")),
        "installs": r.get("installs", ""),
        "score": round(r["score"], 1) if isinstance(r.get("score"), (int, float)) else None,
        "ratings": r.get("ratings"),
        "contentRating": r.get("contentRating", ""),
    })
    return base


def sync_fallback(apps):
    """把本轮结果写进 index.html 的 FALLBACK_ANDROID；内容无变化时不写文件。

    与 iOS 的 add_app.py 保持同一做法：清单 → 数据 → 兜底快照，单一数据源，
    不再需要手工拼 JS 数组（漏逗号会让整页脚本失效）。
    """
    lines = []
    for i, a in enumerate(apps):
        obj = {k: a.get(k) for k in FALLBACK_KEYS}
        comma = "," if i < len(apps) - 1 else ""
        lines.append("    " + json.dumps(obj, ensure_ascii=False) + comma)
    block = "var FALLBACK_ANDROID = [\n" + "\n".join(lines) + "\n  ];"

    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()
    match = re.search(r"var FALLBACK_ANDROID = \[.*?\n  \];", html, re.S)
    if not match:
        print("[兜底] index.html 缺少 FALLBACK_ANDROID 定义，跳过同步")
        return
    if match.group(0) == block:
        return
    with open(INDEX_HTML, "w", encoding="utf-8", newline="\n") as f:
        f.write(html[:match.start()] + block + html[match.end():])
    print("[兜底] 已同步 index.html 内置快照（%d 个包）" % len(apps))


def prev_status(prev, package):
    if not prev:
        return None
    for p in prev.get("apps", []):
        if p.get("packageName") == package or p.get("storeId") == package:
            return p.get("status")
    return None


def build_mail_body(down_apps, checked_at):
    lines = []
    lines.append("【Android 包体监控】有安卓包已下架，请及时处理")
    lines.append("")
    lines.append("检测时间：" + checked_at)
    lines.append("本次共发现 %d 个安卓包已下架：" % len(down_apps))
    lines.append("")
    for i, a in enumerate(down_apps, 1):
        lines.append("%d. %s" % (i, a["name"]))
        lines.append("   · 包名：" + (a.get("packageName") or "-"))
        lines.append("   · 开发者：" + (a.get("developer") or "-"))
        lines.append("   · 商店地址：" + a.get("url", ""))
        lines.append("")
    lines.append("请确认该包是被误下架还是主动下架。")
    lines.append("（此邮件由 Android 监控每日核验触发，请勿直接回复）")
    return "\n".join(lines)


def send_mail(subject, body):
    host = os.environ.get("SMTP_HOST", "").strip()
    port_str = os.environ.get("SMTP_PORT", "465").strip()
    user = os.environ.get("SMTP_USERNAME", "").strip()
    pwd = os.environ.get("SMTP_PASSWORD", "").strip()
    to = (os.environ.get("MAIL_TO", "").strip() or DEFAULT_MAIL_TO).strip()
    if not (host and user and pwd):
        print("[邮件] 未配置 SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD，跳过邮件通知")
        return False
    if not to:
        print("[邮件] 未配置收件人 MAIL_TO，跳过邮件通知")
        return False
    try:
        port = int(port_str)
    except ValueError:
        port = 465
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr(("Android 包体监控", user))
    msg["To"] = to
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.starttls()
        with server:
            server.login(user, pwd)
            server.sendmail(user, [to], msg.as_string())
        print("[邮件] 已发送安卓包下架通知 ->", mask_mail(to))
        return True
    except Exception as e:
        print("[邮件] 发送失败：", e)
        return False


def main():
    skip = throttled()
    if skip:
        print("[节流]", skip)
        print("android total: - online: - offline: - newly_down: - (本轮未核验)")
        return
    apps_cfg = load_apps()
    prev = read_output()
    meta = load_meta()
    now = now_cst().isoformat(timespec="seconds")

    apps = []
    newly_down = []
    for a in apps_cfg:
        info = check_app(a, meta)
        apps.append(info)
        if info["status"] == "online":
            upsert_meta(meta, info)
        elif info["status"] == "offline":
            if prev_status(prev, a["packageName"]) != "offline":
                newly_down.append(info)

    save_meta(meta)

    payload = {"checked_at": now, "apps": apps}
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    sync_fallback(apps)

    if newly_down:
        with open(DOWN_FILE, "w", encoding="utf-8") as f:
            json.dump({"detected_at": now, "down_apps": newly_down}, f, ensure_ascii=False, indent=2)
        send_mail("[Android 监控告警] %d 个包已下架" % len(newly_down), build_mail_body(newly_down, now))
    else:
        if os.path.exists(DOWN_FILE):
            os.remove(DOWN_FILE)

    online = sum(1 for a in apps if a["status"] == "online")
    offline = sum(1 for a in apps if a["status"] == "offline")
    print("checked_at:", payload["checked_at"])
    print("android total:", len(apps), "online:", online, "offline:", offline, "newly_down:", len(newly_down))
    for a in apps:
        print(" -", a["name"], "|", a["status"], "|", a["packageName"] or "-")


if __name__ == "__main__":
    main()
