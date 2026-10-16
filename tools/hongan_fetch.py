#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
红岸加速器 (HongAnapp) 订阅刷新器 —— 只用标准库，Linux/macOS/Windows 都能跑。

它复刻客户端的取配置链路：
    POST /api/v1/passport/auth/login   (邮箱+密码)  -> data.token(订阅token) / data.auth_data(JWT)
    GET  /api/v1/user/getSubscribe     (Authorization: <原始JWT>)  -> subscribe_url
    GET  <subscribe_url>               -> Clash YAML 原文
然后把 YAML 里的节点抽出来，套上本地分组/规则/DNS，生成可直接使用的配置。

用法:
    python3 hongan_fetch.py --email you@x.com --password 'xxx' --out-dir .
    python3 hongan_fetch.py --jwt 'eyJ...' --out-dir .          # 用现成 JWT（会先查 /user/getSubscribe）
    python3 hongan_fetch.py --from-file old_subscription.yaml   # 离线：只做 YAML -> 可用配置 的重建

产物:
    hongan_subscription_raw.yaml   面板下发的原始配置
    hongan_nodes.yaml              可直接喂给 mihomo/Clash 的配置

注意:
  * 认证头必须放**原始 JWT**，写成 "Bearer <jwt>" 会 403。
  * 订阅后端(47.100.65.251:16384)经常挂；挂了会明确报错，并提示走内存重抓(_sub/memscan4.ps1)。
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

API_BASE = "http://hn.luoyaccc.com/api/v1"
UA_DART = "Dart/3.9 (dart:io)"
UA_CLASH = "Clash.Meta/1.19.0"


def http(url, headers=None, data=None, timeout=20):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def login(email, password):
    body = json.dumps({"email": email, "password": password}).encode()
    st, b = http(API_BASE + "/passport/auth/login",
                 {"Content-Type": "application/json", "User-Agent": UA_DART},
                 data=body)
    j = json.loads(b.decode("utf-8", "replace"))
    d = j.get("data") or {}
    if not d.get("auth_data"):
        raise SystemExit(f"登录失败: {b[:300]!r}")
    return d.get("token"), d.get("auth_data")


def user_info(jwt):
    st, b = http(API_BASE + "/user/info", {"Authorization": jwt, "User-Agent": UA_DART})
    return json.loads(b.decode("utf-8", "replace")).get("data") or {}


def get_subscribe(jwt):
    st, b = http(API_BASE + "/user/getSubscribe", {"Authorization": jwt, "User-Agent": UA_DART})
    return json.loads(b.decode("utf-8", "replace")).get("data") or {}


def subscription_candidates(sub_url, token):
    """面板给的订阅地址是 IP:端口；历史版本还用过 App 域名中转，这里都试一遍。"""
    cands = []
    if sub_url:
        cands.append(sub_url)
    if token:
        cands += [
            f"http://hn.luoyaccc.com/api/v2/acct-mgmt?token={token}",
            f"http://hn.hngggg.top/api/v2/acct-mgmt?token={token}",
            f"http://down.xlkooiss.com/api/v2/acct-mgmt?token={token}",
        ]
    seen, out = set(), []
    for u in cands:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def fetch_subscription(sub_url, token):
    errors = []
    for u in subscription_candidates(sub_url, token):
        for hdrs in ({"User-Agent": UA_CLASH}, {"User-Agent": UA_DART}, {"User-Agent": "clash-verge/2.0"}):
            try:
                st, b = http(u, hdrs, timeout=25)
                txt = b.decode("utf-8", "replace")
                if "proxies:" in txt:
                    print(f"[ok] 订阅取回: {u}  ({len(b)} bytes)")
                    return u, txt
                errors.append(f"{u} -> HTTP {st} 但内容不像 Clash 配置({len(b)}B)")
            except Exception as e:
                errors.append(f"{u} -> {type(e).__name__}: {e}")
    print("[!] 所有订阅地址都取不到内容：")
    for e in dict.fromkeys(errors):
        print("    " + e)
    print("    订阅后端大概率挂了（节点本身可能还是活的）。")
    print("    临时办法：在 Windows 客户端里连上内核后，用 _sub/memscan4.ps1 + _sub/extract_cfg.py 从内存重抓。")
    return None, None


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
    return nodes


def block(n):
    L = [f'  - name: "{n["name"]}"',
         f'    type: {n.get("type", "anytls")}',
         f'    server: {n["server"]}',
         f'    port: {n["port"]}',
         f'    password: {n["password"]}']
    for k in ("client-fingerprint", "udp", "alpn", "sni", "skip-cert-verify"):
        if n.get(k):
            L.append(f"    {k}: {n[k]}")
    return "\n".join(L)


def build_config(nodes):
    names = [f'      - "{n["name"]}"' for n in nodes]
    c = [
        "# 红岸加速器 节点配置（由 hongan_fetch.py 生成）",
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--jwt", help="直接给面板 JWT（跳过登录）")
    ap.add_argument("--from-file", help="离线模式：从已有的订阅 YAML 重建可用配置")
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    if a.from_file:
        text = open(a.from_file, encoding="utf-8").read()
        nodes = parse_nodes(text)
    else:
        jwt = a.jwt
        token = None
        if not jwt:
            if not (a.email and a.password):
                raise SystemExit("需要 --email/--password 或 --jwt 或 --from-file")
            token, jwt = login(a.email, a.password)
            print(f"[ok] 登录成功，订阅 token = {token}")
        info = user_info(jwt)
        sub = get_subscribe(jwt)
        used = (sub.get("u") or 0) + (sub.get("d") or 0)
        total = sub.get("transfer_enable") or info.get("transfer_enable")
        gb = 1024 ** 3
        print(f"[ok] 账号 {info.get('email')}  已用 {used / gb:.2f} GB / 总量 {(total or 0) / gb:.2f} GB"
              f"  套餐 {((sub.get('plan') or {}).get('name'))}")
        token = sub.get("subscribe_url", "").split("token=")[-1] or token
        sub_url = sub.get("subscribe_url")
        print(f"[ok] 面板订阅地址 = {sub_url}")
        sub_url_final, text = fetch_subscription(sub_url, token)
        if text is None:
            return 2
        p = os.path.join(a.out_dir, "hongan_subscription_raw.yaml")
        open(p, "w", encoding="utf-8", newline="\n").write(text)
        print(f"[ok] 原始订阅 -> {p}")
        nodes = parse_nodes(text)

    if not nodes:
        raise SystemExit("没解析到任何节点（订阅格式变了？把原始 YAML 发我看一下）")
    real = [n for n in nodes if not re.match(r"(剩余流量|套餐到期|客服QQ)", n.get("name", ""))]
    real = real or nodes
    p2 = os.path.join(a.out_dir, "hongan_nodes.yaml")
    open(p2, "w", encoding="utf-8", newline="\n").write(build_config(real))
    print(f"[ok] 可用配置({len(real)} 个节点) -> {p2}")
    for n in real:
        print(f"      {n['name']}  {n.get('server')}:{n.get('port')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
