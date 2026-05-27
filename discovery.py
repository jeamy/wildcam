import ipaddress
import socket

import requests
from PyQt6.QtCore import QThread, pyqtSignal
from requests.auth import HTTPDigestAuth

from camera_utils import _ssdp_discovery, _udp_reolink_probe, _ws_discovery
from i18n import tr


class CameraDiscoveryThread(QThread):
    """Thread für automatische Kamera-Suche im Netzwerk"""
    camera_found = pyqtSignal(dict)  # {ip, name, model, ports, uid}
    progress_update = pyqtSignal(int, str)
    scan_complete = pyqtSignal(int)
    
    def __init__(self, network_range, ports=None, username="admin", password=""):
        super().__init__()
        self.network_range = network_range
        self.ports = ports or [554, 8000, 80, 8554]  # Typische Reolink/RTSP Ports
        self.username = username
        self.password = password
        self.running = False
        self.found_cameras = []
        
    def run(self):
        """Netzwerk nach Kameras durchsuchen"""
        self.running = True
        self.found_cameras = []
        
        try:
            # 1. Multi-Discovery (UDP Broadcasts)
            self.progress_update.emit(5, "Starte Netzwerk-Suche (UDP/WS/SSDP)...")
            
            discovery_ips = set()
            
            # Reolink BC Discovery
            broadcast_results = _udp_reolink_probe("255.255.255.255", timeout=1.5)
            if broadcast_results and isinstance(broadcast_results, list):
                for info in broadcast_results:
                    discovery_ips.add(info['remote_ip'])
                    camera_info = {
                        'ip': info.get('remote_ip', ''),
                        'ports': [554, 8000, 9000],
                        'name': info.get('name', 'Reolink Camera'),
                        'model': info.get('model', 'Unknown'),
                        'manufacturer': "Reolink",
                        'uid': info.get('devNo', '') or info.get('serial', '')
                    }
                    if camera_info['ip'] not in [c['ip'] for c in self.found_cameras]:
                        self.found_cameras.append(camera_info)
                        self.camera_found.emit(camera_info)

            # ONVIF Discovery
            onvif_ips = _ws_discovery(timeout=1.0)
            discovery_ips.update(onvif_ips)
            
            # SSDP Discovery
            ssdp_ips = _ssdp_discovery(timeout=1.0)
            discovery_ips.update(ssdp_ips)

            # Wenn wir Kameras über Broadcast gefunden haben, prüfen wir diese zuerst
            for dip in discovery_ips:
                if dip not in [c['ip'] for c in self.found_cameras]:
                    # Hole Details für diese IP
                    c_info = self._get_camera_info(dip, [80, 8000, 554, 9000])
                    if c_info:
                        self.found_cameras.append(c_info)
                        self.camera_found.emit(c_info)

            network = ipaddress.ip_network(self.network_range, strict=False)
            total_hosts = network.num_addresses - 2  # Ohne Netzwerk- und Broadcast-Adresse
            checked = 0
            
            for ip in network.hosts():
                if not self.running:
                    break
                
                ip_str = str(ip)
                checked += 1
                self.progress_update.emit(int((checked / total_hosts) * 100), tr("scan.checking", ip=ip_str))
                
                # Schneller Port-Scan
                open_ports = self._scan_ports(ip_str)
                
                if open_ports:
                    # Versuche Kamera-Info abzurufen
                    camera_info = self._get_camera_info(ip_str, open_ports)
                    if camera_info:
                        self.found_cameras.append(camera_info)
                        self.camera_found.emit(camera_info)
            
            self.scan_complete.emit(len(self.found_cameras))
            
        except Exception as e:
            self.progress_update.emit(100, tr("scan.error", error=str(e)))
    
    def _scan_ports(self, ip, timeout=0.5):
        """Schneller Port-Scan für bestimmte IP"""
        open_ports = []
        
        for port in self.ports:
            if not self.running:
                break
            
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                sock.close()
                
                if result == 0:
                    open_ports.append(port)
            except Exception:
                pass
        
        return open_ports
    
    def _get_camera_info(self, ip, ports):
        """Versuche Kamera-Informationen abzurufen"""
        camera_info = {
            'ip': ip,
            'ports': ports,
            'name': tr("camera.default_name.ip", ip=ip),
            'model': tr("camera.meta.unknown"),
            'manufacturer': tr("camera.meta.unknown"),
            'uid': '',
        }
        
        # 1. Versuche UDP Reolink Probe (Port 9000) - am besten für UID & Standby
        udp_info = _udp_reolink_probe(ip)
        if udp_info:
            camera_info['name'] = udp_info.get('name', camera_info['name'])
            camera_info['model'] = udp_info.get('model', camera_info['model'])
            camera_info['manufacturer'] = "Reolink"
            camera_info['uid'] = udp_info.get('devNo', '') or udp_info.get('serial', '')
            return camera_info

        # 2. Versuche ONVIF/HTTP Zugriff
        if 80 in ports or 8000 in ports:
            for port in [80, 8000]:
                if port in ports:
                    try:
                        # Reolink API Versuch
                        url = f"http://{ip}:{port}/api.cgi?cmd=GetDevInfo"
                        response = requests.get(
                            url, 
                            auth=HTTPDigestAuth(self.username, self.password),
                            timeout=2
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            if isinstance(data, list) and len(data) > 0:
                                info = data[0].get('value', {}).get('DevInfo', {})
                                camera_info['name'] = info.get('name', camera_info['name'])
                                camera_info['model'] = info.get('model', camera_info['model'])
                                camera_info['manufacturer'] = "Reolink"
                                camera_info['uid'] = info.get('devNo', '') or info.get('serial', '')
                                return camera_info
                    except Exception:
                        pass
        
        # Wenn HTTP nicht funktioniert, aber RTSP Port offen ist
        if 554 in ports or 8554 in ports:
            camera_info['manufacturer'] = tr("camera.meta.rtsp_camera")
            return camera_info
        
        return None
    
    def stop(self):
        """Scan stoppen"""
        self.running = False
