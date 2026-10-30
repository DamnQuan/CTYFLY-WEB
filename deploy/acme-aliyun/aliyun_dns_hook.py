#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""certbot manual hook —— 通过阿里云云解析完成 DNS-01 验证。

certbot 会以 `auth` / `cleanup` 两个参数调用本脚本，并通过环境变量传入：

    CERTBOT_DOMAIN 正在验证的域名，泛域名会去掉开头的 "*."
    CERTBOT_VALIDATION 需要写进 TXT 记录的校验值
    CERTBOT_CERT_NAME 证书名，仅用于日志

凭据从下列位置按顺序查找，第一个存在且可读的生效：

    1. 环境变量 ALIYUN_DNS_INI 指定的文件
    2. /etc/ctyfly/aliyun-dns.ini
    3. ~/.aliyun-dns.ini

文件格式，等号分隔，可带 # 注释：

    accessKeyId=LTAI...
    accessKeySecret=...
    # 可选：显式指定主域名，留空则自动探测
    zone=ccflysim.cn

只依赖 Python 标准库，不需要 pip 安装任何东西。
"""

import base64
import hashlib
import hmac
import json
import os
import random
import socket
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API_HOST = "alidns.aliyuncs.com"
API_VERSION = "2015-01-09"
RECORD_TTL = 600
PROPAGATION_TIMEOUT = 120
CHALLENGE = "_acme-challenge"

INI_CANDIDATES = (
    os.environ.get("ALIYUN_DNS_INI", "/etc/letsencrypt/aliyun-dns.ini"),
    "/etc/ctyfly/aliyun-dns.ini",
    os.path.expanduser("~/.aliyun-dns.ini"),
)


def log(msg):
    sys.stderr.write("[aliyun-dns] %s\n" % msg)
    sys.stderr.flush()


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------
def load_config():
    path = None
    for candidate in INI_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            path = candidate
            break

    cfg = {}
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                cfg[key.strip()] = val.strip()
        log("凭据文件: %s" % path)
    else:
        log("未找到凭据文件，改用环境变量")

    cfg.setdefault("accessKeyId", os.environ.get("ALIYUN_ACCESS_KEY_ID", ""))
    cfg.setdefault("accessKeySecret", os.environ.get("ALIYUN_ACCESS_KEY_SECRET", ""))
    cfg.setdefault("zone", os.environ.get("ALIYUN_DNS_ZONE", ""))

    if not cfg["accessKeyId"] or not cfg["accessKeySecret"]:
        raise SystemExit(
            "缺少 accessKeyId / accessKeySecret，请检查 %s" % (path or "环境变量")
        )
    return cfg


# --------------------------------------------------------------------------
# 阿里云 RPC 签名，v1，HMAC-SHA1
# --------------------------------------------------------------------------
def _pe(value):
    return urllib.parse.quote(str(value), safe="~")


class AliyunDNS(object):
    def __init__(self, ak_id, ak_secret):
        self.ak_id = ak_id
        self.ak_secret = ak_secret

    def call(self, action, **params):
        query = {
            "Format": "JSON",
            "Version": API_VERSION,
            "AccessKeyId": self.ak_id,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": str(uuid.uuid4()),
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "Action": action,
        }
        for key, val in params.items():
            if val is not None:
                query[key] = val

        canonical = "&".join(
            "%s=%s" % (_pe(k), _pe(v)) for k, v in sorted(query.items())
        )
        string_to_sign = "GET&%s&%s" % (_pe("/"), _pe(canonical))
        digest = hmac.new(
            (self.ak_secret + "&").encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        query["Signature"] = base64.b64encode(digest).decode("ascii")

        url = "https://%s/?%s" % (
            API_HOST,
            "&".join("%s=%s" % (k, _pe(v)) for k, v in query.items()),
        )
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                data = json.loads(body)
            except ValueError:
                data = {"Code": "HTTP%d" % exc.code, "Message": body[:300]}
            if data.get("Code") in ("Throttling", "Throttling.User", "ServiceUnavailable"):
                log("接口限流，5 秒后重试: %s" % action)
                time.sleep(5)
                return self.call(action, **params)
            raise RuntimeError(
                "%s 调用失败: %s %s" % (action, data.get("Code"), data.get("Message"))
            )

    # ---- 主域名与主机记录 ------------------------------------------------
    def find_zone(self, domain):
        parts = domain.split(".")
        for idx in range(len(parts) - 1):
            candidate = ".".join(parts[idx:])
            try:
                self.call("DescribeDomainInfo", DomainName=candidate)
                return candidate
            except RuntimeError:
                continue
        raise RuntimeError("阿里云账号下找不到 %s 的解析域名" % domain)

    def zone_ns(self, zone):
        try:
            info = self.call("DescribeDomainInfo", DomainName=zone)
        except RuntimeError:
            return []
        servers = (info.get("DnsServers") or {}).get("DnsServer") or []
        return [s for s in servers if s]

    def list_txt(self, zone, rr):
        data = self.call(
            "DescribeDomainRecords",
            DomainName=zone,
            RRKeyWord=rr,
            Type="TXT",
            PageSize=200,
        )
        records = (data.get("DomainRecords") or {}).get("Record") or []
        return [r for r in records if r.get("RR") == rr]

    def add_txt(self, zone, rr, value):
        for rec in self.list_txt(zone, rr):
            if rec.get("Value") == value:
                log("记录已存在，跳过新增: %s.%s" % (rr, zone))
                return rec.get("RecordId")
        data = self.call(
            "AddDomainRecord",
            DomainName=zone,
            RR=rr,
            Type="TXT",
            Value=value,
            TTL=RECORD_TTL,
        )
        log("已新增 TXT: %s.%s = %s" % (rr, zone, value))
        return data.get("RecordId")

    def del_txt(self, zone, rr, value=None):
        removed = 0
        for rec in self.list_txt(zone, rr):
            if value is not None and rec.get("Value") != value:
                continue
            self.call("DeleteDomainRecord", RecordId=rec.get("RecordId"))
            removed += 1
            log("已删除 TXT: %s.%s" % (rr, zone))
        if not removed:
            log("没有需要删除的 TXT 记录: %s.%s" % (rr, zone))
        return removed


# --------------------------------------------------------------------------
# 权威 NS 传播轮询，标准库手写 DNS 查询，避免依赖 dig/dnspython
# --------------------------------------------------------------------------
def _skip_name(data, offset):
    while True:
        if offset >= len(data):
            return len(data)
        length = data[offset]
        if length == 0:
            return offset + 1
        if length & 0xC0 == 0xC0:
            return offset + 2
        offset += 1 + length


def query_txt(ns, name, timeout=5):
    """向指定 NS 查询 TXT 记录，返回字符串列表，失败返回空列表。"""
    qid = random.randint(0, 0xFFFF)
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    question = b""
    for label in name.rstrip(".").split("."):
        raw = label.encode("idna") if any(ord(c) > 127 for c in label) else label.encode("ascii")
        question += bytes([len(raw)]) + raw
    question += b"\x00" + struct.pack(">HH", 16, 1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(header + question, (ns, 53))
        data, _ = sock.recvfrom(8192)
    except Exception:
        return []
    finally:
        sock.close()

    if len(data) < 12:
        return []
    try:
        _, _, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", data[:12])
        offset = 12
        for _ in range(qdcount):
            offset = _skip_name(data, offset) + 4
        values = []
        for _ in range(ancount):
            offset = _skip_name(data, offset)
            rtype, _, _, rdlength = struct.unpack(">HHIH", data[offset:offset + 10])
            offset += 10
            rdata = data[offset:offset + rdlength]
            offset += rdlength
            if rtype != 16:
                continue
            cursor, chunks = 0, []
            while cursor < len(rdata):
                length = rdata[cursor]
                chunks.append(
                    rdata[cursor + 1:cursor + 1 + length].decode("utf-8", "replace")
                )
                cursor += 1 + length
            values.append("".join(chunks))
        return values
    except Exception:
        return []


def wait_propagation(zone, rr, value, servers):
    name = "%s.%s" % (rr, zone)
    if not servers:
        servers = ["223.5.5.5", "119.29.29.29"]
    deadline = time.time() + PROPAGATION_TIMEOUT
    while True:
        if all(value in query_txt(ns, name) for ns in servers):
            log("权威 NS 已生效: %s (%s)" % (name, ", ".join(servers)))
            return True
        if time.time() >= deadline:
            log("警告：%ss 内未在所有权威 NS 上看到校验值，仍继续交给 ACME 校验" % PROPAGATION_TIMEOUT)
            return False
        time.sleep(4)


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("auth", "cleanup"):
        raise SystemExit("用法: %s auth|cleanup" % sys.argv[0])

    mode = sys.argv[1]
    domain = os.environ.get("CERTBOT_DOMAIN", "").strip()
    value = os.environ.get("CERTBOT_VALIDATION", "").strip()
    if not domain or not value:
        raise SystemExit("缺少 CERTBOT_DOMAIN / CERTBOT_VALIDATION 环境变量")

    cfg = load_config()
    client = AliyunDNS(cfg["accessKeyId"], cfg["accessKeySecret"])

    zone = cfg["zone"].strip() or client.find_zone(domain)
    if domain == zone:
        rr = CHALLENGE
    else:
        if not domain.endswith("." + zone):
            raise SystemExit("域名 %s 不属于主域名 %s" % (domain, zone))
        rr = "%s.%s" % (CHALLENGE, domain[: -(len(zone) + 1)])

    if mode == "auth":
        client.add_txt(zone, rr, value)
        wait_propagation(zone, rr, value, client.zone_ns(zone))
    else:
        client.del_txt(zone, rr, value)


if __name__ == "__main__":
    main()
