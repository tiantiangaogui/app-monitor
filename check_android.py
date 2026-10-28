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

DEFAULT_MAIL_TO = ""


def load_apps():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def now_cst():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def last_checked_at():
    if not os.path.exists(OUTPUT):
        return None
    try:
        with open(OUTPUT, encoding="utf-8") as f:
            return json.load(f).get("checked_at")
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
    raw = last_checked_at()
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


def check_app(app, meta):
    now = now_cst().isoformat(timespec="seconds")
    pkg = app["packageName"]
    base = {
        "storeId": pkg,
        "packageName": pkg,
        "name": app["name"],
        "url": app["url"],
        "status": "unknown",
        "checkedAt": now,
        "developer": "",
        "bundleId": pkg,
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
    try:
        r = fetch_play(pkg, app.get("country", "us"), app.get("lang", "en"))
        if r is None:
            base["status"] = "offline"
            snap = (meta.get("apps") or {}).get(pkg)
            if snap:
                for k in ("developer", "genre", "releaseDate", "version", "icon"):
                    base[k] = snap.get(k, "")
                base["infoSnapshot"] = True
                base["snapshotAt"] = snap.get("updatedAt", "")
            return base
        base["status"] = "online"
        base["name"] = r.get("title") or app["name"]
        base["developer"] = r.get("developer", "")
        base["packageName"] = pkg
        base["bundleId"] = pkg
        base["genre"] = r.get("genre", "")
        base["releaseDate"] = to_iso_date(r.get("released", ""))
        base["version"] = r.get("version", "")
        base["icon"] = r.get("icon", "")
        base["updatedDate"] = to_iso_from_ts(r.get("updated"))
        base["installs"] = r.get("installs", "")
        base["score"] = r.get("score")
        base["ratings"] = r.get("ratings")
        base["contentRating"] = r.get("contentRating", "")
        base["url"] = "https://play.google.com/store/apps/details?id=" + pkg
        return base
    except Exception:
        # 网络异常：保留未确认状态，不误报下架
        base["status"] = "unknown"
        return base


def load_prev():
    if os.path.exists(OUTPUT):
        try:
            with open(OUTPUT, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


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
        server.login(user, pwd)
        server.sendmail(user, [to], msg.as_string())
        server.quit()
        print("[邮件] 已发送安卓包下架通知 ->", to)
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
    prev = load_prev()
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
