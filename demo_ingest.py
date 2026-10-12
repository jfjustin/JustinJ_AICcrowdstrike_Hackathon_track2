#!/usr/bin/env python3
"""Demo the live ingest endpoint against a running app.

    python -m app.main        # in one terminal (http://127.0.0.1:8713)
    python demo_ingest.py     # in another

Fires a synthetic attack burst (webshell probes + DNS exfil on 10.9.8.7,
benign noise on 10.9.8.8, one raw AMiner-shaped alert) and prints what the
pipeline did with it: new chains vs. attachments to existing incidents.
"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8713"
now = time.time()
alerts = []

# --- attack burst on a fresh host: webshell probing (apache) ---
for i in range(40):
    alerts.append({
        "ts": now - 300 + i * 7,
        "host": "10.9.8.7",
        "detector": "NewMatchPathDetector",
        "detector_name": "New event type",
        "log_source": "/var/log/apache2/intranet-access.log",
        "message": f'10.9.8.7 - - [..] "GET /wp-content/uploads/shell{i}.php?cmd=id HTTP/1.1" 200 512 "-" "curl/8.0"',
    })

# --- DNS exfiltration burst (high entropy) ---
for i in range(12):
    alerts.append({
        "ts": now - 120 + i * 9,
        "host": "10.9.8.7",
        "detector": "EntropyDetector",
        "detector_name": "High entropy in DNS domain",
        "log_source": "/var/log/dnsmasq.log",
        "message": f"query[A] chunk{i}.aB3dE9xQ2kL7mN4pR8sT1uVwY.example.evil",
    })

# --- benign noise on another host ---
for i in range(15):
    alerts.append({
        "ts": now - 200 + i * 13,
        "host": "10.9.8.8",
        "detector": "NewMatchPathValueDetector",
        "detector_name": "New value",
        "log_source": "/var/log/apache2/intranet-access.log",
        "message": '10.9.8.8 - - [..] "GET /index.html HTTP/1.1" 200 1234 "-" "Mozilla/5.0"',
        "values": ["200"],
    })

# --- one raw AMiner-shaped alert (proves both input shapes work) ---
alerts.append({
    "AnalysisComponent": {
        "AnalysisComponentType": "NewMatchPathDetector",
        "AnalysisComponentName": "AMiner: New event type.",
        "TrainingMode": False,
    },
    "LogData": {
        "RawLogData": ["Oct 12 14:00:01 web sshd[1234]: Failed password for root from 10.9.8.7 port 51234"],
        "Timestamps": [now - 60],
        "DetectionTimestamp": [now - 60],
        "LogLinesCount": 1,
        "LogResources": ["/var/log/auth.log"],
    },
    "AMiner": {"ID": "10.9.8.7"},
})

body = json.dumps({"scenario": "live-demo", "alerts": alerts}).encode()
req = urllib.request.Request(
    BASE + "/api/ingest", data=body, headers={"Content-Type": "application/json"})
resp = json.loads(urllib.request.urlopen(req).read())
print(json.dumps(resp, indent=2))
print("\nNow open the queue — the new incident(s) should be at/near the top.")
