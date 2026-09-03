# -*- coding: utf-8 -*-
"""
一键添加快捷工具
用法：
    python add_app.py <App Store 链接或 storeId> [country]

示例：
    python add_app.py https://apps.apple.com/us/app/xxx/id6772021868
    python add_app.py 6772021868
    python add_app.py 6772021868 us

作用：
    1. 自动解析 storeId 与地区，向 App Store 官方接口核实 App 是否存在
    2. 追加到 apps.json（清单单一数据源）
    3. 重新生成 data.json
    4. 自动同步 index.html 的内置快照（FALLBACK_APPS），本地预览也立即生效
"""
import io
import json
import os
import re
import sys
import subprocess
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APPS_JSON = os.path.join(BASE_DIR, "apps.json")
DATA_JSON = os.path.join(BASE_DIR, "data.json")
INDEX_HTML = os.path.join(BASE_DIR, "index.html")


def parse_input(arg, country_arg):
    """从链接或纯 ID 中解析出 (storeId, country, url)"""
    arg = arg.strip().strip('"').strip("'")
    # 纯数字 ID
    if re.fullmatch(r"\d+", arg):
        store_id = arg
        country = (country_arg or "us").lower()
        url = "https://apps.apple.com/%s/app/id%s" % (country, store_id)
        return store_id, country, url
    # 完整 App Store 链接
    m_id = re.search(r"/id(\d+)", arg)
    if not m_id:
        sys.exit("无法从输入中解析出 storeId，请提供形如 https://apps.apple.com/us/app/xxx/id6772021868 的链接或纯数字 ID")
    store_id = m_id.group(1)
    m_cc = re.search(r"apps\.apple\.com/([a-z]{2})/", arg)
    country = (m_cc.group(1) if m_cc else (country_arg or "us")).lower()
    url = "https://apps.apple.com/%s/app/id%s" % (country, store_id)
    return store_id, country, url


def lookup(store_id, country):
    """向 App Store 官方接口核实，返回结果 dict 或 None"""
    url = "https://itunes.apple.com/lookup?id=%s&country=%s" % (store_id, country)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 add-app"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("resultCount", 0) > 0:
        return data["results"][0]
    return None


def load_apps():
    with open(APPS_JSON, encoding="utf-8") as f:
        return json.load(f)


def save_apps(apps):
    with open(APPS_JSON, "w", encoding="utf-8") as f:
        json.dump(apps, f, ensure_ascii=False, indent=2)
        f.write("\n")


def rerun_check():
    """重新运行检测脚本生成 data.json"""
    subprocess.run([sys.executable, os.path.join(BASE_DIR, "check_status.py")], check=True, cwd=BASE_DIR)


def build_fallback_js(data):
    """从 data.json 生成 index.html 里 FALLBACK_APPS 的 JS 数组代码"""
    lines = ["var FALLBACK_APPS = ["]
    apps = data.get("apps", [])
    for i, a in enumerate(apps):
        obj = {
            "name": a.get("name", ""),
            "developer": a.get("developer", ""),
            "bundleId": a.get("bundleId", ""),
            "releaseDate": a.get("releaseDate", ""),
            "version": a.get("version", ""),
            "url": a.get("url", ""),
            "icon": a.get("icon", ""),
            "status": a.get("status", "unknown"),
        }
        comma = "," if i < len(apps) - 1 else ""
        lines.append("  " + json.dumps(obj, ensure_ascii=False) + comma)
    lines.append("];")
    return "\n".join(lines)


def sync_fallback_to_html():
    """把 data.json 的最新结果同步进 index.html 的 FALLBACK_APPS"""
    with open(DATA_JSON, encoding="utf-8") as f:
        data = json.load(f)
    js_block = build_fallback_js(data)
    with io.open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()
    new_html, n = re.subn(
        r"var FALLBACK_APPS = \[.*?\];",
        lambda m: js_block,
        html,
        count=1,
        flags=re.S,
    )
    if n == 0:
        sys.exit("index.html 中未找到 FALLBACK_APPS 定义，已停止同步（请检查文件结构）")
    with io.open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(new_html)
    print("已同步 index.html 内置快照（%d 个 App）" % len(data.get("apps", [])))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    store_id, country, url = parse_input(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)

    # 1. 核实
    r = lookup(store_id, country)
    if r is None:
        sys.exit("在 App Store（%s 区）未找到 storeId=%s 的应用，请检查链接或地区代码" % (country.upper(), store_id))
    track_name = r.get("trackName", store_id)

    # 2. 查重
    apps = load_apps()
    if any(a["storeId"] == store_id for a in apps):
        print("该包已在监控列表：%s（storeId=%s），无需重复添加" % (track_name, store_id))
        return

    # 3. 追加
    apps.append({
        "name": track_name,
        "storeId": store_id,
        "country": country,
        "url": url,
    })
    save_apps(apps)
    print("已添加：%s（storeId=%s，%s 区）" % (track_name, store_id, country.upper()))

    # 4. 重新生成 data.json
    rerun_check()
    print("已重新生成 data.json（共 %d 个 App）" % len(apps))

    # 5. 同步 index.html 快照
    sync_fallback_to_html()

    print("完成！把改动 push 到 GitHub 后即纳入每日自动核验；想立即生效可在 Actions 手动 Run 一次。")


if __name__ == "__main__":
    main()
