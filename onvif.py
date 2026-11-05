"""Minimal ONVIF client: WS-Discovery, device info and stream URI lookup.

Only the few SOAP calls WildCam needs, without extra dependencies.
"""
import base64
import calendar
import hashlib
import os
import re
import socket
import time
import uuid
from urllib.parse import unquote, urlparse

import requests

WS_DISCOVERY_ADDR = ("239.255.255.250", 3702)

_PROBE_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"'
    ' xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"'
    ' xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
    "<e:Header>"
    "<w:MessageID>uuid:{message_id}</w:MessageID>"
    '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
    '<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
    "</e:Header>"
    "<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>"
    "</e:Envelope>"
)


def _scope_value(scopes: list[str], key: str) -> str:
    prefix = f"onvif://www.onvif.org/{key}/"
    for scope in scopes:
        if scope.startswith(prefix):
            return unquote(scope[len(prefix):]).replace("_", " ").strip()
    return ""


def parse_probe_match(xml_text: str) -> dict:
    """Extract XAddrs and the name/hardware scopes from a ProbeMatch."""
    xaddrs_match = re.search(r"<(?:\w+:)?XAddrs>([^<]*)</", xml_text)
    scopes_match = re.search(r"<(?:\w+:)?Scopes[^>]*>([^<]*)</", xml_text)
    xaddrs = xaddrs_match.group(1).split() if xaddrs_match else []
    scopes = scopes_match.group(1).split() if scopes_match else []
    return {
        "xaddrs": xaddrs,
        "name": _scope_value(scopes, "name"),
        "hardware": _scope_value(scopes, "hardware"),
        "mac": _scope_value(scopes, "MAC") or _scope_value(scopes, "mac"),
    }


def ws_discovery(timeout: float = 3.0, repeats: int = 3) -> dict[str, dict]:
    """ONVIF WS-Discovery. Returns {ip: probe_match_info}.

    Each probe carries a fresh, valid MessageID (devices drop malformed
    probes) and is sent several times because UDP multicast is lossy.
    """
    results: dict[str, dict] = {}
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.2)
        start = time.monotonic()
        deadline = start + timeout
        interval = timeout / max(1, repeats)
        sent = 0
        while time.monotonic() < deadline:
            # Spread the probes over the listen window instead of a burst.
            if sent < max(1, repeats) and time.monotonic() >= start + sent * interval:
                message = _PROBE_TEMPLATE.format(message_id=uuid.uuid4())
                sock.sendto(message.encode("utf-8"), WS_DISCOVERY_ADDR)
                sent += 1
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            if addr[0] in results:
                continue
            info = parse_probe_match(data.decode("utf-8", "ignore"))
            if info["xaddrs"]:
                results[addr[0]] = info
    except OSError:
        pass
    finally:
        if sock is not None:
            sock.close()
    return results


# Ports on which cameras commonly serve ONVIF (Tapo: 2020, many OEMs: 8899).
ONVIF_PORTS = (80, 2020, 8000, 8899, 5000)


def device_service_urls(ip: str, info: dict | None, open_ports=()) -> list[str]:
    """Candidate device-service URLs: discovered XAddrs first, then open ONVIF ports."""
    xaddrs = list((info or {}).get("xaddrs", []))
    urls = [x for x in xaddrs if urlparse(x).hostname == ip] + [x for x in xaddrs if urlparse(x).hostname != ip]
    for port in ONVIF_PORTS:
        if port in open_ports:
            suffix = "" if port == 80 else f":{port}"
            url = f"http://{ip}{suffix}/onvif/device_service"
            if url not in urls:
                urls.append(url)
    return urls


def find_onvif_service(ip: str, info: dict | None, open_ports=(), timeout: float = 2.0) -> str:
    """Return the first URL answering an unauthenticated GetSystemDateAndTime."""
    for url in device_service_urls(ip, info, open_ports):
        client = OnvifClient(url, timeout=timeout)
        try:
            text = client.call(url, '<GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>', auth=False)
        except Exception:
            continue
        if "GetSystemDateAndTimeResponse" in text:
            return url
    return ""


class OnvifClient:
    """Tiny SOAP client with WS-Security UsernameToken (PasswordDigest)."""

    def __init__(self, device_url: str, username: str = "", password: str = "", timeout: float = 4.0):
        self.device_url = device_url
        self.username = username
        self.password = password
        self.timeout = timeout
        self._time_offset = 0.0

    def _security_header(self) -> str:
        if not self.username:
            return ""
        nonce = os.urandom(16)
        created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + self._time_offset))
        digest = hashlib.sha1(nonce + created.encode() + self.password.encode()).digest()
        return (
            '<s:Header><Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/'
            'oasis-200401-wss-wssecurity-secext-1.0.xsd"><UsernameToken>'
            f"<Username>{_xml_escape(self.username)}</Username>"
            '<Password Type="http://docs.oasis-open.org/wss/2004/01/'
            f'oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{base64.b64encode(digest).decode()}</Password>'
            '<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/'
            f'oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</Nonce>'
            '<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">'
            f"{created}</Created></UsernameToken></Security></s:Header>"
        )

    def call(self, url: str, body: str, auth: bool = True) -> str:
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
            f"{self._security_header() if auth else ''}<s:Body>{body}</s:Body></s:Envelope>"
        )
        response = requests.post(
            url,
            data=envelope.encode("utf-8"),
            headers={"Content-Type": "application/soap+xml; charset=utf-8"},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise OnvifError(f"HTTP {response.status_code}")
        return response.text

    def sync_time(self):
        """Use the device clock for digests (cameras reject skewed timestamps)."""
        try:
            text = self.call(
                self.device_url,
                '<GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>',
                auth=False,
            )
        except Exception:
            return
        utc = re.search(r"<(?:\w+:)?UTCDateTime>(.*?)</(?:\w+:)?UTCDateTime>", text, re.S)
        if not utc:
            return
        fields = {}
        for key in ("Year", "Month", "Day", "Hour", "Minute", "Second"):
            match = re.search(rf"<(?:\w+:)?{key}>(\d+)<", utc.group(1))
            if not match:
                return
            fields[key] = int(match.group(1))
        device_ts = calendar.timegm((
            fields["Year"], fields["Month"], fields["Day"],
            fields["Hour"], fields["Minute"], fields["Second"], 0, 0, 0,
        ))
        self._time_offset = device_ts - time.time()

    def device_information(self) -> dict:
        text = self.call(self.device_url, '<GetDeviceInformation xmlns="http://www.onvif.org/ver10/device/wsdl"/>')
        info = {}
        for key in ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber"):
            match = re.search(rf"<(?:\w+:)?{key}>([^<]*)<", text)
            info[key.lower()] = match.group(1).strip() if match else ""
        return info

    def media_url(self) -> str:
        text = self.call(
            self.device_url,
            '<GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl"><Category>Media</Category></GetCapabilities>',
        )
        match = re.search(r"<(?:\w+:)?Media>\s*<(?:\w+:)?XAddr>([^<]+)<", text)
        return match.group(1).strip() if match else self.device_url

    def stream_uri(self) -> str:
        """RTSP URI of the first media profile (usually the main stream)."""
        media = self.media_url()
        profiles = self.call(media, '<GetProfiles xmlns="http://www.onvif.org/ver10/media/wsdl"/>')
        token = re.search(r'<(?:\w+:)?Profiles[^>]*\btoken="([^"]+)"', profiles)
        if not token:
            raise OnvifError("no media profile")
        text = self.call(
            media,
            '<GetStreamUri xmlns="http://www.onvif.org/ver10/media/wsdl">'
            '<StreamSetup><Stream xmlns="http://www.onvif.org/ver10/schema">RTP-Unicast</Stream>'
            '<Transport xmlns="http://www.onvif.org/ver10/schema"><Protocol>RTSP</Protocol></Transport>'
            "</StreamSetup>"
            f"<ProfileToken>{_xml_escape(token.group(1))}</ProfileToken></GetStreamUri>",
        )
        uri = re.search(r"<(?:\w+:)?Uri>([^<]+)<", text)
        if not uri:
            raise OnvifError("no stream uri")
        return _xml_unescape(uri.group(1).strip())


class OnvifError(RuntimeError):
    pass


def _xml_escape(value: str) -> str:
    return (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _xml_unescape(value: str) -> str:
    return value.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")


def probe_onvif_device(ip: str, info: dict | None, username: str, password: str, open_ports=()) -> dict:
    """Best-effort: device information and RTSP stream URI via ONVIF.

    Returns {} if no ONVIF service answers.
    """
    url = find_onvif_service(ip, info, open_ports)
    if not url:
        return {}
    client = OnvifClient(url, username, password)
    client.sync_time()
    result = {"onvif_url": url}
    try:
        result.update(client.device_information())
    except Exception:
        pass
    if username:
        try:
            result["stream_uri"] = client.stream_uri()
        except Exception:
            pass
    return result
