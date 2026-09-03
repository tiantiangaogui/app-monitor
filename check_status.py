# -*- coding: utf-8 -*-
"""
App 包体在线状态检测脚本
- 逐个查询 App Store 官方 iTunes Search API，判断每个 App 是否在线可下载
- 生成 data.json，供 index.html 动态加载渲染
- 设计为可在 GitHub Actions 上每日定时运行（跨平台，仅用 Python 标准库）
"""
import json
import os
import datetime
import urllib.request

# 输出始终写到脚本所在目录，保证本地与 CI 行为一致
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(BASE_DIR, "data.json")
CONFIG = os.path.join(BASE_DIR, "apps.json")


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


def main():
    apps = [check_app(a) for a in load_apps()]
    payload = {
        "checked_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds"),
        "apps": apps,
    }
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    # 输出摘要到 stdout，便于 Actions 日志查看
    online = sum(1 for a in apps if a["status"] == "online")
    print("checked_at:", payload["checked_at"])
    print("total:", len(apps), "online:", online, "offline:", sum(1 for a in apps if a["status"] == "offline"))
    for a in apps:
        print(" -", a["name"], "|", a["status"], "|", a["bundleId"] or "-")


if __name__ == "__main__":
    main()
