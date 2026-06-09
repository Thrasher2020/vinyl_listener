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

# Load config from Home Assistant options
with open('/data/options.json') as f:
    config = json.load(f)

# --- CONFIGURATION ---
MQTT_HOST = config.get('mqtt_host')
MQTT_PORT = 1883
MQTT_USER = config.get('mqtt_user')
MQTT_PASSWORD = config.get('mqtt_password')
ACR_KEY = config.get('acr_access_key')
ACR_SECRET = config.get('acr_access_secret')
TURNTABLE_ENTITY = config.get('turntable_entity', 'switch.turntable')
REQUIRED_SILENCE_SEC = config.get('silence_gap_seconds', 2)
ACR_HOST = "identify-eu-west-1.acrcloud.com"

# --- TUNING PARAMETERS ---
VOLUME_THRESHOLD = 500  

# Initialize Clients
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.loop_start()
shazam = Shazam()

def setup_mqtt_discovery():
    """Publishes device and sensor configurations to Home Assistant via MQTT Auto-Discovery."""
    print("Publishing MQTT Auto-Discovery configuration...")
    
    device_info = {
        "identifiers": ["vinyl_listener_addon"],
        "name": "Vinyl Listener",
        "manufacturer": "Thrasher2020",
        "model": "Hybrid Audio Scrobbler"
    }

    artist_config = {
        "name": "Vinyl Artist",
        "unique_id": "vinyl_listener_artist",
        "state_topic": "home/vinyl/now_playing",
        "value_template": "{{ value_json.artist }}",
        "icon": "mdi:account-music",
        "device": device_info
    }

    title_config = {
        "name": "Vinyl Title",
        "unique_id": "vinyl_listener_title",
        "state_topic": "home/vinyl/now_playing",
        "value_template": "{{ value_json.title }}",
        "icon": "mdi:music-circle",
        "device": device_info
    }

    art_config = {
        "name": "Vinyl Album Art",
        "unique_id": "vinyl_listener_art",
        "state_topic": "home/vinyl/now_playing",
        "value_template": "{{ value_json.album_art }}",
        "icon": "mdi:image-album",
        "device": device_info
    }

    client.publish("homeassistant/sensor/vinyl_listener/artist/config", json.dumps(artist_config), retain=True)
    client.publish("homeassistant/sensor/vinyl_listener/title/config", json.dumps(title_config), retain=True)
    client.publish("homeassistant/sensor/vinyl_listener/album_art/config", json.dumps(art_config), retain=True)

# Run discovery immediately upon startup
setup_mqtt_discovery()

def is_turntable_on():
    """Checks the state of the user-defined switch via the HA Supervisor API."""
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        print("⚠️ WARNING: No SUPERVISOR_TOKEN found!")
        return False
        
    url = f"http://supervisor/core/api/states/{TURNTABLE_ENTITY}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Host": "supervisor" 
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json().get("state") == "on"
    except Exception:
        pass
    return False

def get_local_volume():
    """Records 1 second of raw PCM audio and calculates peak amplitude."""
    process = subprocess.run([
        "arecord", "-D", "pulse", "-d", "1", "-f", "S16_LE", "-r", "16000", "-t", "raw"
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if process.returncode != 0:
        err = process.stderr.decode('utf-8', errors='ignore').strip()
        print(f"⚠️ Microphone hardware error: {err}")
        return 0
        
    data = process.stdout
    if not data:
        return 0
        
    count = len(data) // 2
    shorts = struct.unpack(f"{count}h", data)
    if shorts:
        return max(abs(x) for x in shorts)
    return 0

def identify_acrcloud(file_path):
    """Fallback cloud identification via ACRCloud API."""
    http_method = "POST"
    http_uri = "/v1/identify"
    data_type = "audio"
    signature_version = "1"
    timestamp = str(int(time.time()))

    string_to_sign = '\n'.join([http_method, http_uri, ACR_KEY, data_type, signature_version, timestamp])
    sign = base64.b64encode(hmac.new(ACR_SECRET.encode('ascii'), string_to_sign.encode('ascii'), digestmod=hashlib.sha1).digest()).decode('ascii')

    files = {'sample': open(file_path, 'rb')}
    data = {
        'access_key': ACR_KEY,
        'sample_bytes': os.path.getsize(file_path),
        'timestamp': timestamp,
        'signature': sign,
        'data_type': data_type,
        "signature_version": signature_version
    }
    
    try:
        r = requests.post(f"https://{ACR_HOST}{http_uri}", files=files, data=data, timeout=10)
        return r.json()
    except Exception:
        return None

async def identify_hybrid(file_path):
    """Attempts free local Shazam identification first, falls back to ACRCloud if configured."""
    try:
        out = await shazam.recognize(file_path)
        if out and 'track' in out:
            return {
                'title': out['track']['title'], 
                'artist': out['track']['subtitle'], 
                'source': 'Shazam'
            }
    except Exception:
        pass

    if ACR_KEY and ACR_SECRET:
        print("Shazam failed, falling back to ACRCloud...")
        out = identify_acrcloud(file_path)
        if out and out.get('status', {}).get('msg') == 'Success':
            metadata = out['metadata']['music'][0]
            title = metadata.get('title', 'Unknown')
            artist = metadata['artists'][0].get('name', 'Unknown') if metadata.get('artists') else 'Unknown'
            return {
                'title': title, 
                'artist': artist, 
                'source': 'ACRCloud'
            }
            
    return None

def get_album_art(artist, title):
    """Fetches high-res album art from the free iTunes Search API."""
    try:
        url = "https://itunes.apple.com/search"
        params = {
            "term": f"{artist} {title} Metal",
            "media": "music",
            "limit": 5
        }
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        
        if data.get('resultCount', 0) > 0:
            for result in data['results']:
                if artist.lower() in result.get('artistName', '').lower():
                    low_res_url = result.get('artworkUrl100', '')
                    return low_res_url.replace('100x100bb', '600x600bb')
    except Exception:
        pass
    return ""

def main_loop():
    print("Vinyl Listener hybrid service started. Listening for turntable...")
    
    in_track_lock = False
    silence_seconds = 0
    next_retry_time = 0
    last_turntable_state = None
    
    while True:
        turntable_on = is_turntable_on()
        
        # Log state changes for the switch (quiet heartbeat)
        if turntable_on != last_turntable_state:
            print(f"🎛️ Turntable switch ({TURNTABLE_ENTITY}) monitored state changed to: {'ON' if turntable_on else 'OFF'}")
            last_turntable_state = turntable_on

        if not turntable_on:
            in_track_lock = False
            silence_seconds = 0
            time.sleep(5)
            continue
            
        volume = get_local_volume()
        
        if in_track_lock:
            if volume < VOLUME_THRESHOLD:
                silence_seconds += 1
                if silence_seconds >= REQUIRED_SILENCE_SEC:
                    print(f"🎵 Track gap detected ({REQUIRED_SILENCE_SEC}s of silence). Arming for next song.")
                    in_track_lock = False
                    silence_seconds = 0
            else:
                silence_seconds = 0
        else:
            if volume >= VOLUME_THRESHOLD:
                if time.time() < next_retry_time:
                    time.sleep(1)
                    continue
                    
                print("🔊 Audio threshold crossed! Capturing fingerprint sample...")
                process = subprocess.run([
                    "arecord", "-D", "pulse", "-d", "8", "-f", "cd", "/tmp/sample.wav"
                ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                
                if process.returncode != 0:
                    print(f"⚠️ Sample capture failed: {process.stderr.strip()}")
                    continue
                    
                result = asyncio.run(identify_hybrid("/tmp/sample.wav"))
                
                if result:
                    art = get_album_art(result['artist'], result['title'])
                    payload = {
                        "title": result['title'],
                        "artist": result['artist'],
                        "album_art": art
                    }
                    print(f"🔥 NEW TRACK DETECTED via {result['source']}: {result['artist']} - {result['title']}")
                    client.publish("home/vinyl/now_playing", json.dumps(payload), retain=True)
                    in_track_lock = True
                    silence_seconds = 0
                else:
                    print("Audio detected but no metadata match found. cooling down 15s...")
                    next_retry_time = time.time() + 15
                    
                if os.path.exists('/tmp/sample.wav'):
                    os.remove('/tmp/sample.wav')
                    
        time.sleep(1)

if __name__ == "__main__":
    main_loop()
