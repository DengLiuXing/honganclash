#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""红岸加速器 (HongAnapp) 配置获取器 v2 —— 纯标准库，Linux/macOS/Windows 通用。

三级兜底，任何一级成功都能产出可用配置：
  [1] 订阅后端：登录 -> /user/getSubscribe -> subscribe_url -> Clash YAML（最权威）
  [2] 本地生成：账号 uuid 当节点密码 + 内置节点模板 + 端口 TCP 存活校验（后端挂掉时生效）
  [3] 缓存快照：hongan_template.json（模板/端口/uuid），断网也能出结果

用法：
  python3 hongan_fetch.py --email you@x.com --password 'xxx'
  python3 hongan_fetch.py --from-client          # Windows：从红岸客户端配置里读账号
  python3 hongan_fetch.py --jwt 'eyJ...'
  python3 hongan_fetch.py --from-file raw.yaml   # 离线：只重建
  python3 hongan_fetch.py --from-client --verify # 生成后用本地 mihomo 实测一次

默认【直连】，不读系统代理/环境代理：红岸客户端会把系统代理改成 127.0.0.1:7892，
Windows 上 urllib 会自动继承注册表代理，于是请求全绕到代理上返回假 502。
要走代理请显式 --proxy http://127.0.0.1:7890

产物：
  hongan_nodes.yaml            可用配置（mihomo/FlClash 直接导入）
  hongan_template.json         模板缓存（下次后端挂掉时的依据）
  hongan_subscription_raw.yaml 订阅成功时另存的面板原始 YAML
"""
import argparse
import gzip
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API_BASE = "http://hn.luoyaccc.com/api/v1"
# 面板 API 的 UA，按客户端抓包原值
UA_DART = "Mozilla/5.0 (dart:io) SuperAccelerator"
# 订阅接口只认这一个 UA：2026-11-01 抓包确认，换任何其他 UA 一律 HTTP 444
UA_SUB = "NetFlow/v2.2.8 clash-verge Platform/windows"
NODE_HOST = "hn.hngggg.top"
NODE_SNI = "down.xlkooiss.com"
INFO_PORT = 27609  # 套餐信息节点占用的端口，不是真节点

# 内置模板（2026-10 从面板订阅还原；订阅恢复后会自动用面板的新端口覆盖它）
DEFAULT_PORTS = [
    ("香港1 稳定入口", 27611), ("香港2 稳定入口", 27612), ("香港3 稳定入口", 27613),
    ("台湾1 稳定入口", 27621), ("台湾2 稳定入口", 27622),
    ("日本1 稳定入口", 27631), ("日本2 稳定入口", 27632), ("日本3 稳定入口", 27633),
    ("新加坡1 稳定入口", 27641), ("新加坡2 稳定入口", 27642), ("新加坡3 稳定入口", 27643),
    ("美国1 稳定入口", 27651), ("美国2 稳定入口", 27652),
    ("韩国1 稳定入口", 27661), ("韩国2 稳定入口", 27662),
    ("加拿大 稳定入口", 27671), ("泰国 稳定入口", 27678), ("马来西亚 稳定入口", 27679),
]

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def set_proxy(proxy):
    global _OPENER
    if proxy:
        _OPENER = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
        print(f"[i] 走代理: {proxy}")
    else:
        _OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        print("[i] 直连（已屏蔽系统代理）")


def http(url, headers=None, data=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with _OPENER.open(req, timeout=timeout) as r:
        body = r.read()
        if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
            try:
                body = gzip.decompress(body)
            except OSError:
                pass
        return r.status, body


def get_json(url, headers=None, timeout=15):
    _, b = http(url, headers, timeout=timeout)
    return json.loads(b.decode("utf-8", "replace"))


def login(email, password):
    body = json.dumps({"email": email, "password": password}).encode()
    _, b = http(API_BASE + "/passport/auth/login",
                {"Content-Type": "application/json", "User-Agent": UA_DART},
                data=body, timeout=20)
    j = json.loads(b.decode("utf-8", "replace"))
    d = j.get("data") or {}
    if not d.get("auth_data"):
        raise SystemExit(f"登录失败: {json.dumps(j, ensure_ascii=False)[:300]}")
    return d.get("token"), d.get("auth_data")


def api_data(path, jwt):
    j = get_json(API_BASE + path, {"Authorization": jwt, "User-Agent": UA_DART})
    return j.get("data") or {}


RATE_LIMITED = "RATE_LIMITED"
ENCRYPTED = "ENCRYPTED"
_B64_RE = re.compile(r"^[A-Za-z0-9+/=\s]{512,}$")


def candidates(sub_url, token):
    """只有 hn.luoyaccc.com 会回 HTTP：另外两个域名 80 端口直接关连接，问了也白问。"""
    urls = []
    if sub_url:
        urls.append(sub_url.replace("&amp;", "&"))
    if token:
        urls.append(f"http://hn.luoyaccc.com/api/v2/acct-mgmt?token={token}")
    out, seen = [], set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def fetch_subscription(sub_url, token):
    """返回 (url, text, errors)。

    两个结论都来自 2026-11-01 的抓包（pktmon，见 hongan/_pcap_*）：
    1. 订阅接口按 User-Agent 白名单放行，只认官方那个 UA，别的一律 HTTP 444（空 body）；
    2. 放行后返回的是红岸自家格式：base64 文本包着的加密块（熵 7.996，不是 gzip），
       Clash 客户端无法直接使用——只有红岸客户端自己会解。
    所以这里能拿到「最新订阅已更新」和流量统计，但拿不到明文节点；明文仍靠本地模板。
    """
    errors = []
    for u in candidates(sub_url, token):
        try:
            _, b = http(u, {"User-Agent": UA_SUB, "Accept-Encoding": "gzip"}, timeout=40)
        except urllib.error.HTTPError as e:
            if e.code == 444:
                errors.append(f"{u} -> HTTP 444（UA 不在白名单，面板直接掐断）")
                errors.append(RATE_LIMITED)
                break
            errors.append(f"{u} -> HTTP {e.code}")
            continue
        except Exception as e:
            errors.append(f"{u} -> {type(e).__name__}")
            continue
        txt = b.decode("utf-8", "replace")
        if "proxies:" in txt or "proxy-groups:" in txt:
            return u, txt, errors
        if _B64_RE.match(txt.strip()) and len(txt.strip()) > 4096:
            errors.append(f"{u} -> HTTP 200，返回红岸加密订阅（{len(txt)} 字符 base64，"
                          f"明文约 {len(txt) * 3 // 4}B 密文，标准 Clash 无法解析）")
            errors.append(ENCRYPTED)
            continue
        errors.append(f"{u} -> HTTP 200 但内容不是 Clash 配置({len(b)}B)")
    return None, None, list(dict.fromkeys(errors))


NODE_RE = re.compile(r"\s*-\s*\{(.*)\}\s*$")


def parse_nodes(text):
    nodes = []
    for line in text.split("\n"):
        m = NODE_RE.match(line)
        if not m:
            continue
        kv = {}
        for part in re.split(r",\s*(?![^\[]*\])", m.group(1)):
            if ":" not in part:
                continue
            k, v = part.split(":", 1)
            kv[k.strip()] = v.strip().strip("'")
        if "name" in kv and "server" in kv:
            nodes.append(kv)
    # 块状写法（完整配置的 proxies: 段）
    cur = None
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("- name:"):
            cur = {"name": s[len("- name:"):].strip().strip('"').strip("'")}
            nodes.append(cur)
        elif cur is not None and line.startswith(" ") and ":" in s:
            k, v = s.split(":", 1)
            if k.strip() in ("server", "port", "password"):
                cur[k.strip()] = v.strip().strip('"').strip("'")
        elif s and not line.startswith(" "):
            cur = None
    return [n for n in nodes
            if n.get("name") and n.get("server") and n.get("port")]


def template_path(out_dir):
    return os.path.join(out_dir, "hongan_template.json")


def load_template(out_dir):
    try:
        j = json.load(open(template_path(out_dir), encoding="utf-8"))
        nodes = [(str(n["name"]), int(n["port"])) for n in j.get("nodes", [])]
        if nodes:
            return nodes, j.get("uuid")
    except Exception:
        pass
    return list(DEFAULT_PORTS), None


def save_template(out_dir, nodes, uuid):
    data = {
        "host": NODE_HOST,
        "sni": NODE_SNI,
        "uuid": uuid,
        "updated": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "nodes": [{"name": n["name"], "port": int(n["port"])} for n in nodes],
    }
    with open(template_path(out_dir), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


SUB_STATE = "_sub_state.json"
SUB_RAW = "hongan_subscription_raw.yaml"
SUB_COOLDOWN = 6 * 3600  # 订阅接口有 token 级限流，默认 6 小时内不再碰它
SERVERS_CACHE = "hongan_servers.json"


def save_servers_cache(out_dir, servers):
    p = os.path.join(out_dir, SERVERS_CACHE)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"saved": time.strftime("%Y-%m-%d %H:%M:%S"), "servers": servers},
                  f, ensure_ascii=False, indent=2)


def load_servers_cache(out_dir):
    p = os.path.join(out_dir, SERVERS_CACHE)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("servers")
    except (OSError, ValueError):
        return None


def load_sub_state(out_dir):
    try:
        with open(os.path.join(out_dir, SUB_STATE), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_sub_state(out_dir, **kw):
    st = load_sub_state(out_dir)
    st.update(kw)
    with open(os.path.join(out_dir, SUB_STATE), "w", encoding="utf-8", newline="\n") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def cached_raw(out_dir):
    p = os.path.join(out_dir, SUB_RAW)
    try:
        with open(p, encoding="utf-8") as f:
            txt = f.read()
        if "proxies:" in txt:
            return p, txt
    except Exception:
        pass
    return None, None


def probe(host, ports, timeout=3, workers=24):
    def one(p):
        s = socket.socket()
        s.settimeout(timeout)
        try:
            s.connect((host, p))
            return p
        except Exception:
            return None
        finally:
            s.close()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return {p for p in ex.map(one, ports) if p}


def parse_ports(spec):
    ports = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            ports.update(range(int(a), int(b) + 1))
        else:
            ports.add(int(part))
    return sorted(ports)


def discover(ports, uuid, mihomo_bin, workers=8, timeout_ms=3000):
    """用真 mihomo 对候选端口逐个做 anytls 延迟测试：只有协议层握手成功的才算活。"""
    import shutil
    import subprocess
    import time

    exe = shutil.which(mihomo_bin)
    if not exe:
        print(f"[!] 找不到 {mihomo_bin}，跳过端口发现")
        return None
    tmp = os.path.join(os.getcwd(), ".hongan-verify")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, "discover.yaml")
    ctrl = free_port()
    nodes = [node(f"P{p}", p, uuid) for p in ports]
    cfg = ["mixed-port: %d" % free_port(), "allow-lan: false", "mode: rule",
           "log-level: warning", f"external-controller: 127.0.0.1:{ctrl}", "",
           "proxies:", "\n".join(block(n) for n in nodes), "",
           "rules:\n  - MATCH,DIRECT"]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(cfg) + "\n")
    proc = subprocess.Popen([exe, "-d", tmp, "-f", path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    api = f"http://127.0.0.1:{ctrl}"
    one_ok = False
    deadline = time.time() + 20
    while time.time() < deadline and proc.poll() is None:
        try:
            with urllib.request.urlopen(api + "/version", timeout=2) as r:
                if r.status == 200:
                    one_ok = True
                    break
        except Exception:
            time.sleep(0.5)

    def delay(p):
        try:
            u = (f"{api}/proxies/P{p}/delay"
                 f"?url=http://cp.cloudflare.com/generate_204&timeout={timeout_ms}")
            with urllib.request.urlopen(u, timeout=timeout_ms / 1000 + 3) as r:
                j = json.loads(r.read().decode("utf-8"))
            return p if j.get("delay") else None
        except Exception:
            return None

    found = []
    if one_ok:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            found = [p for p in ex.map(delay, ports) if p]
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    shutil.rmtree(tmp, ignore_errors=True)
    return sorted(found) if one_ok else None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def verify(nodes, mihomo_bin, timeout=25):
    """起一个临时 mihomo，只带这批节点，通过它请求一次 204 探针。"""
    import shutil
    import subprocess
    import tempfile
    import time

    exe = shutil.which(mihomo_bin)
    if not exe:
        print(f"[!] 找不到 {mihomo_bin}，跳过验证（把它放进 PATH 或 --mihomo 指定路径）")
        return None
    port = free_port()
    names = [n["name"] for n in nodes]
    cfg = ["mixed-port: %d" % port, "allow-lan: false", "mode: rule", "log-level: warning", ""]
    cfg.append("proxies:\n" + "\n".join(block(n) for n in nodes))
    cfg.append("proxy-groups:")
    cfg.append("  - name: P\n    type: select\n    proxies:\n" + "\n".join(f'      - "{x}"' for x in names))
    cfg.append("rules:\n  - MATCH,P")
    # 注意：不要用 tempfile.mkdtemp —— 它建的目录在部分受限环境下不可写。
    tmp = os.path.join(os.getcwd(), ".hongan-verify")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, "verify.yaml")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(cfg) + "\n")

    proc = subprocess.Popen([exe, "-d", tmp, "-f", path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = False
    deadline = time.time() + timeout
    proxy = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    while time.time() < deadline and proc.poll() is None:
        try:
            with opener.open("http://cp.cloudflare.com/generate_204", timeout=8) as r:
                if r.status == 204:
                    ok = True
                    break
        except Exception:
            time.sleep(1)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    print(f"[{'ok' if ok else '!'}] mihomo 实测: {'代理可用（204）' if ok else '未通过（节点失效/需要 TUN/被墙）'}")
    shutil.rmtree(tmp, ignore_errors=True)
    return ok


def node(name, port, uuid, host=None, sni=None, insecure=0):
    return {"name": name, "port": int(port), "password": uuid,
            "host": host or NODE_HOST, "sni": sni or NODE_SNI,
            "insecure": int(insecure or 0)}


def nodes_from_template(template, uuid, alive):
    out = []
    for name, port in template:
        if port == INFO_PORT:
            continue
        if alive is not None and port not in alive:
            continue
        out.append(node(name, port, uuid))
    return out


def nodes_from_servers(servers, uuid):
    """把面板 /user/server/fetch 的明文节点表转成本工具的内部结构。

    这是目前唯一「既有明文、又由面板自己维护」的来源：字段 host/port/server_name
    就是节点真实参数，is_online 还能过滤掉下线的机器。
    """
    out = []
    for s in servers:
        try:
            port = int(s.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if not port or port == INFO_PORT:
            continue
        if str(s.get("type") or "").lower() != "anytls":
            continue
        if s.get("is_online") in (0, "0", False):
            continue
        name = (s.get("name") or f"节点{port}").strip()
        out.append(node(name, port, uuid,
                        host=s.get("host"),
                        sni=s.get("server_name"),
                        insecure=s.get("insecure")))
    out.sort(key=lambda n: n["port"])
    return out


def block(n):
    return "\n".join([
        f'  - name: "{n["name"]}"',
        "    type: anytls",
        f'    server: {n.get("host") or NODE_HOST}',
        f'    port: {n["port"]}',
        f'    password: {n["password"]}',
        "    client-fingerprint: chrome",
        "    udp: true",
        "    alpn: [h2, http/1.1]",
        f'    sni: {n.get("sni") or NODE_SNI}',
        f'    skip-cert-verify: {"true" if n.get("insecure") else "false"}',
    ])


def build_config(nodes, uuid_hint):
    names = [f'      - "{n["name"]}"' for n in nodes]
    c = [
        "# 红岸加速器 节点配置（由 hongan_fetch.py 生成）",
        f"# 账号 uuid(=节点密码): {uuid_hint}",
        "# 用法: mihomo -f hongan_nodes.yaml  /  FlClash → 配置 → 添加 → 从文件导入",
        "",
        "mixed-port: 7890",
        "allow-lan: false",
        'bind-address: "*"',
        "mode: rule",
        "log-level: info",
        "ipv6: false",
        "unified-delay: true",
        "tcp-concurrent: true",
        "find-process-mode: always",
        "keep-alive-interval: 30",
        "geodata-loader: memconservative",
        "external-controller: 127.0.0.1:9090",
        "",
        "dns:",
        "  enable: true",
        "  ipv6: false",
        "  enhanced-mode: fake-ip",
        "  fake-ip-range: 198.18.0.1/16",
        "  fake-ip-filter:",
        '    - "*.lan"',
        "    - localhost.ptlogin2.qq.com",
        "  default-nameserver: [223.5.5.5, 119.29.29.29]",
        '  nameserver: ["https://doh.pub/dns-query", "https://dns.alidns.com/dns-query"]',
        '  fallback: ["tls://8.8.4.4", "tls://1.1.1.1"]',
        '  proxy-server-nameserver: ["https://doh.pub/dns-query"]',
        "  fallback-filter: { geoip: true, geoip-code: CN, geosite: [gfw], ipcidr: [240.0.0.0/4] }",
        "",
        "proxies:",
        "\n".join(block(n) for n in nodes),
        "",
        "proxy-groups:",
        "  - name: 自动选择",
        "    type: url-test",
        "    url: http://cp.cloudflare.com/generate_204",
        "    interval: 300",
        "    tolerance: 50",
        "    proxies:",
        *names,
        "  - name: 手动选择",
        "    type: select",
        "    proxies:",
        "      - 自动选择",
        *names,
        "      - DIRECT",
        "  - name: 红岸云",
        "    type: select",
        "    proxies:",
        "      - 手动选择",
        "      - 自动选择",
        "      - DIRECT",
        "  - name: 漏网之鱼",
        "    type: select",
        "    proxies:",
        "      - 手动选择",
        "      - DIRECT",
        "",
        "rules:",
        "  - DOMAIN-SUFFIX,local,DIRECT",
        "  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
        "  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
        "  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
        "  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
        "  - IP-CIDR6,fc00::/7,DIRECT,no-resolve",
        "  - GEOSITE,cn,DIRECT",
        "  - GEOIP,CN,DIRECT",
        "  - MATCH,漏网之鱼",
        "",
    ]
    return "\n".join(c)


def creds_from_client():
    paths = [
        os.path.expandvars(r"%APPDATA%\HongAnapp\HongAnapp\shared_preferences.json"),
        os.path.expanduser("~/.config/HongAnapp/HongAnapp/shared_preferences.json"),
    ]
    for p in paths:
        try:
            j = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if j.get("flutter.email") and j.get("flutter.password"):
            print(f"[i] 从客户端配置读取账号: {p}")
            return j["flutter.email"], j["flutter.password"], j.get("flutter.auth_token")
    return None


def refresh_by_discover(template, uuid, args):
    """用 --discover 重新发现端口，返回新的 (name, port) 模板。"""
    ports = parse_ports(args.ports)
    print(f"[i] 端口发现 {args.ports}：用 mihomo 逐个做 anytls 实测，约 {max(20, len(ports) // 4)} 秒")
    found = discover(ports, uuid, args.mihomo)
    if found is None:
        print("[!] 没有可用的 mihomo（用 --mihomo 指定路径，或放进 PATH），跳过端口发现")
        return template
    if not found:
        print("[!] 端口发现一个都没通（节点全挂或本地 mihomo 起不来），沿用现有模板")
        return template
    names = {port: name for name, port in template}
    missed = [p for _, p in template if p not in found]
    if missed:
        print(f"[i] 模板里 {len(missed)} 个端口首轮没通，加长超时重测: {missed}")
        again = discover(missed, uuid, args.mihomo, workers=4, timeout_ms=8000)
        if again:
            found = sorted(set(found) | set(again))
            print(f"[i] 重测后合计 {len(found)} 个")
    print(f"[i] 协议层实测可用端口 {len(found)} 个: {', '.join(str(p) for p in found)}")
    return [(names.get(p, f"节点{p}"), p) for p in found]


def write_out(out_dir, nodes, uuid, verify_bin=None):
    p = os.path.join(out_dir, "hongan_nodes.yaml")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_config(nodes, uuid))
    print(f"[ok] 可用配置({len(nodes)} 个节点) -> {p}")
    for n in nodes:
        print(f"      {n['name']}  {NODE_HOST}:{n['port']}")
    if verify_bin and verify(nodes, verify_bin):
        print("[ok] 配置已实测可用")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--jwt", help="直接给面板 JWT（跳过登录）")
    ap.add_argument("--from-client", action="store_true", help="从红岸客户端配置读账号")
    ap.add_argument("--from-file", help="离线模式：从已有订阅 YAML 重建")
    ap.add_argument("--no-check", action="store_true", help="跳过端口连通性探测")
    ap.add_argument("--verify", action="store_true", help="用本地 mihomo 实测生成的配置")
    ap.add_argument("--discover", action="store_true",
                    help="用 mihomo 逐端口实测 anytls，重新发现存活节点（不依赖模板）")
    ap.add_argument("--ports", default="27600-27699", help="--discover 的端口范围，默认 27600-27699")
    ap.add_argument("--mihomo", default="mihomo", help="mihomo 可执行文件（默认 PATH 里的 mihomo）")
    ap.add_argument("--proxy", help="显式代理，如 http://127.0.0.1:7890")
    ap.add_argument("--force", action="store_true", help="无视订阅接口的 6 小时冷却，强制请求一次")
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()

    out_dir = os.path.expanduser(a.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    set_proxy(a.proxy)

    if a.from_file:
        text = open(a.from_file, encoding="utf-8").read()
        parsed = parse_nodes(text)
        nodes = [{"name": n["name"], "port": int(n["port"]), "password": n.get("password", "")}
                 for n in parsed if not re.match(r"(剩余流量|套餐到期|客服QQ)", n.get("name", ""))]
        if not nodes:
            raise SystemExit("没从文件里解析到节点")
        save_template(out_dir, nodes, nodes[0]["password"])
        return write_out(out_dir, nodes, nodes[0]["password"], a.mihomo if a.verify else None)

    template, cached_uuid = load_template(out_dir)
    uuid = cached_uuid
    token = jwt = None
    email = password = None

    if a.jwt:
        jwt = a.jwt
    elif a.email and a.password:
        email, password = a.email, a.password
    else:
        got = creds_from_client()
        if got:
            email, password, jwt = got
    if not jwt and not (email and password) and not uuid:
        raise SystemExit("需要 --email/--password、--jwt、--from-client、--from-file；"
                         "或先联网跑一次留下 hongan_template.json")

    sub = info = {}
    if not jwt and not (email and password):
        # 离线：只用缓存里的 uuid + 模板，一个请求都不发
        print(f"[i] 无账号凭据，用缓存 uuid 离线生成: {uuid}")
        if a.discover:
            template = refresh_by_discover(template, uuid, a)
        nodes = nodes_from_template(template, uuid, None)
        if not nodes:
            raise SystemExit("缓存模板为空，先联网跑一次")
        save_template(out_dir, nodes, uuid)
        return write_out(out_dir, nodes, uuid, a.mihomo if a.verify else None)
    try:
        if not jwt:
            token, jwt = login(email, password)
            print(f"[ok] 登录成功，订阅 token = {token}")
        info = api_data("/user/info", jwt)
        sub = api_data("/user/getSubscribe", jwt)
        uuid = sub.get("uuid") or info.get("uuid") or uuid
        used = (sub.get("u") or 0) + (sub.get("d") or 0)
        total = sub.get("transfer_enable") or info.get("transfer_enable") or 0
        gb = 1024 ** 3
        print(f"[ok] 账号 {info.get('email') or email}  已用 {used / gb:.2f} GB / 总量 {total / gb:.2f} GB"
              f"  套餐 {(sub.get('plan') or {}).get('name')}")
        token = token or urllib.parse.parse_qs(
            urllib.parse.urlparse(sub.get("subscribe_url", "")).query).get("token", [None])[0]
    except SystemExit:
        raise
    except Exception as e:
        print(f"[!] 面板 API 不可用: {type(e).__name__}: {e}")
        if not uuid:
            _, uuid = load_template(out_dir)
        if not uuid:
            raise SystemExit("面板 API 不可用，且没有缓存的 uuid；先联网跑一次，或 --from-file")

    # ---- 零级：面板明文节点表（最可靠：明文、面板自己维护、带 is_online）----
    servers = None
    if jwt and uuid:
        try:
            servers = api_data("/user/server/fetch", jwt)
            if isinstance(servers, list) and servers:
                save_servers_cache(out_dir, servers)
        except Exception as e:
            print(f"[!] 面板节点表暂不可用: {type(e).__name__}: {e}")
            servers = load_servers_cache(out_dir)
            if servers:
                print(f"[i] 改用上次缓存的节点表（{len(servers)} 条，可能已过期）")
        if isinstance(servers, list) and servers:
            nodes0 = nodes_from_servers(servers, uuid)
            if nodes0:
                save_template(out_dir, nodes0, uuid)
                print(f"[ok] 面板明文节点表: {len(servers)} 条记录 → {len(nodes0)} 个在线 anytls 节点")
                return write_out(out_dir, nodes0, uuid, a.mihomo if a.verify else None)

    # ---- 一级：订阅接口（UA 白名单放行；返回加密订阅，只用于确认「还活着」）----
    text = None
    if jwt:
        sub_url = sub.get("subscribe_url")
        print(f"[i] 面板订阅地址 = {sub_url}")
        state = load_sub_state(out_dir)
        age = time.time() - (state.get("last_attempt") or 0)
        if not a.force and age < SUB_COOLDOWN:
            print(f"[i] 距上次请求订阅接口 {age / 60:.0f} 分钟，本次跳过（--force 强制）")
        else:
            save_sub_state(out_dir, last_attempt=time.time())
            sub_url2, text, errors = fetch_subscription(sub_url, token)
            if text:
                save_sub_state(out_dir, last_ok=time.time(), ok_url=sub_url2)
                p = os.path.join(out_dir, SUB_RAW)
                with open(p, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                print(f"[ok] 订阅取回: {sub_url2}")
                print(f"[ok] 原始订阅 -> {p}")
                parsed = parse_nodes(text)
                real = [{"name": n["name"], "port": int(n["port"]), "password": n.get("password", uuid)}
                        for n in parsed if not re.match(r"(剩余流量|套餐到期|客服QQ)", n.get("name", ""))]
                if real:
                    save_template(out_dir, real, uuid)
                    return write_out(out_dir, real, uuid, a.mihomo if a.verify else None)
            elif RATE_LIMITED in errors:
                print("[!] 订阅接口返回 HTTP 444：这个 UA 不在面板白名单里。")
                print(f"    真机客户端用的是「{UA_SUB}」，脚本已内置；若仍 444，说明面板换了白名单。")
                for e in errors:
                    if e != RATE_LIMITED:
                        print("    " + e)
            elif ENCRYPTED in errors:
                print("[ok] 订阅接口放行（HTTP 200），但返回的是红岸加密格式，标准 Clash 用不了。")
                print("    这条路只能确认「订阅还活着」；节点明文走本地模板 + 账号 uuid。")
                for e in errors:
                    if e != ENCRYPTED:
                        print("    " + e)
            else:
                print("[!] 订阅取回失败：")
                for e in errors:
                    print("    " + e)
        if not text:
            raw_path, cached = cached_raw(out_dir)
            if cached:
                print(f"[i] 用上次成功抓到的订阅缓存: {raw_path}")
                parsed = parse_nodes(cached)
                real = [{"name": n["name"], "port": int(n["port"]), "password": n.get("password", uuid)}
                        for n in parsed if not re.match(r"(剩余流量|套餐到期|客服QQ)", n.get("name", ""))]
                if real:
                    save_template(out_dir, real, uuid)
                    return write_out(out_dir, real, uuid, a.mihomo if a.verify else None)

    # ---- 二级：账号 uuid + 模板 + 存活校验 ----
    if not uuid:
        raise SystemExit("缺少 uuid，无法本地生成")
    print(f"[i] 走本地生成：uuid={uuid}  模板={len(template)} 个端口")
    if a.discover:
        template = refresh_by_discover(template, uuid, a)
    alive = None
    if not a.no_check and not a.discover:
        alive = probe(NODE_HOST, [p for _, p in template] + [INFO_PORT])
        print(f"[i] 端口连通: {len(alive)}/{len(template) + 1}  ({NODE_HOST})"
              f"  —— 只证明主机可达，不代表节点可用，节点是否真能代理用 --verify 实测")

    nodes = nodes_from_template(template, uuid, alive)
    if not nodes:
        raise SystemExit("模板端口全部不可达：换网络重试，或换一条网络/节点再跑")
    save_template(out_dir, nodes, uuid)
    print(f"[i] 生成来源: 本地模板 + 账号 uuid（订阅后端不可用时的兜底）")
    return write_out(out_dir, nodes, uuid, a.mihomo if a.verify else None)


if __name__ == "__main__":
    sys.exit(main())
