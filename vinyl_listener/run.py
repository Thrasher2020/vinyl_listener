import os
import time
import json
import struct
import subprocess
import hmac
import hashlib
import base64
import requests
import paho.mqtt.client as mqtt
import asyncio
from shazamio import Shazam

# Load config variables
with open('/data/options.json') as f:
    config = json.load(f)

MQTT_HOST = config.get('mqtt_host')
MQTT_PORT = config.get('mqtt_port')
MQTT_USER = config.get('mqtt_user')
MQTT_PASSWORD = config.get('mqtt_password')
ACR_KEY = config.get('acr_access_key')
ACR_SECRET = config.get('acr_access_secret')

# --- TUNING PARAMETERS ---
VOLUME_THRESHOLD = 500  
REQUIRED_SILENCE_SEC = 2  

# Initialize Clients
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.loop_start()
shazam = Shazam()

def is_turntable_on():
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token: return False
    url = "http://supervisor/core/api/states/switch.turntable"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Host": "supervisor"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        return response.status_code == 200 and response.json().get("state") == "on"
    except Exception: return False

def get_local_volume():
    process = subprocess.run(["arecord", "-D", "default", "-d", "1", "-f", "S16_LE", "-r", "16000", "-t", "raw"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if not process.stdout: return 0
    shorts = struct.unpack(f"{len(process.stdout)//2}h", process.stdout)
    return max(abs(x) for x in shorts) if shorts else 0

async def identify_hybrid(file_path):
    # 1. Try local Shazam (Free)
    try:
        out = await shazam.recognize(file_path)
        if out and 'track' in out:
            return {'title': out['track']['title'], 'artist': out['track']['subtitle']}
    except Exception: pass

    # 2. Fallback to ACRCloud (Cloud) if keys provided
    if ACR_KEY and ACR_SECRET:
        # (Insert your previous ACRCloud logic here)
        pass
    return None

def get_album_art(artist, title):
    try:
        url = "https://itunes.apple.com/search"
        params = {"term": f"{artist} {title} Metal", "media": "music", "limit": 5}
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        if data.get('resultCount', 0) > 0:
            for result in data['results']:
                if artist.lower() in result.get('artistName', '').lower():
                    return result.get('artworkUrl100', '').replace('100x100bb', '600x600bb')
    except Exception: pass
    return ""

def main_loop():
    print("Vinyl Listener hybrid service started.")
    in_track_lock = False
    silence_seconds = 0
    
    while True:
        if not is_turntable_on():
            in_track_lock = False
            time.sleep(10)
            continue
            
        volume = get_local_volume()
        if in_track_lock:
            if volume < VOLUME_THRESHOLD:
                silence_seconds += 1
                if silence_seconds >= REQUIRED_SILENCE_SEC: in_track_lock = False
            else: silence_seconds = 0
        elif volume >= VOLUME_THRESHOLD:
            subprocess.run(["arecord", "-D", "default", "-d", "8", "-f", "cd", "/tmp/sample.wav"], stdout=subprocess.DEVNULL)
            result = asyncio.run(identify_hybrid("/tmp/sample.wav"))
            if result:
                art = get_album_art(result['artist'], result['title'])
                payload = {"title": result['title'], "artist": result['artist'], "album_art": art}
                client.publish("home/vinyl/now_playing", json.dumps(payload), retain=True)
                in_track_lock = True
                silence_seconds = 0
            if os.path.exists('/tmp/sample.wav'): os.remove('/tmp/sample.wav')

if __name__ == "__main__":
    main_loop()
