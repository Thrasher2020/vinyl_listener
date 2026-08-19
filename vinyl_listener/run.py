import os
import sys
import time
import json
import struct
import subprocess
import hmac
import hashlib
import base64
import requests
import signal
import paho.mqtt.client as mqtt
import asyncio
from shazamio import Shazam
import pylast
import acoustid

# Load config from Home Assistant options
with open('/data/options.json') as f:
    config = json.load(f)

# --- CONFIGURATION ---
MQTT_HOST = config.get('mqtt_host')
MQTT_PORT = 1883
MQTT_USER = config.get('mqtt_user')
MQTT_PASSWORD = config.get('mqtt_password')

ACOUSTID_API_KEY = config.get('acoustid_api_key')
ACR_KEY = config.get('acr_access_key')
ACR_SECRET = config.get('acr_access_secret')
ACR_HOST = "identify-eu-west-1.acrcloud.com"

TURNTABLE_ENTITY = config.get('turntable_entity', 'switch.turntable')
REQUIRED_SILENCE_SEC = config.get('silence_gap_seconds', 2)
IDLE_IMAGE = config.get('idle_image_url', '')

# New Features Configuration
AUTO_CALIBRATE = config.get('auto_calibrate', True)
MANUAL_THRESHOLD = config.get('manual_threshold', 500)
LASTFM_ENABLED = config.get('lastfm_enabled', False)
LASTFM_KEY = config.get('lastfm_api_key')
MAX_RETRIES = config.get('max_retries', 3)
SAMPLE_DELAY = config.get('sample_delay_seconds', 5)
DEBUG_MODE = config.get('debug_mode', False)

# Initialize global threshold
global_volume_threshold = MANUAL_THRESHOLD

def get_local_volume():
    process = subprocess.run([
        "arecord", "-D", "pulse", "-d", "1", "-f", "S16_LE", "-r", "16000", "-t", "raw"
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if process.returncode != 0:
        return 0
        
    data = process.stdout
    if not data:
        return 0
        
    count = len(data) // 2
    shorts = struct.unpack(f"{count}h", data)
    return max(abs(x) for x in shorts) if shorts else 0

def calibrate_noise_floor():
    """Samples the room for 5 seconds to set a dynamic volume threshold."""
    print("🎧 Auto-calibrating noise floor. Sampling background noise...")
    peaks = []
    for _ in range(5):
        peaks.append(get_local_volume())
        time.sleep(0.5)
        
    avg_peak = sum(peaks) / len(peaks)
    new_threshold = max(300, int(avg_peak * 2.5))
    print(f"✅ Calibration complete! Ambient noise average: {int(avg_peak)}. Threshold locked at: {new_threshold}")
    return new_threshold

# 1. DEFINE MQTT MESSAGE CALLBACK FIRST
def on_message(client, userdata, msg):
    global global_volume_threshold
    
    if msg.topic == "home/vinyl/command/calibrate":
        print("👆 Manual calibration triggered via Home Assistant!")
        global_volume_threshold = calibrate_noise_floor()

# 2. INITIALIZE CLIENTS
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
client.on_message = on_message
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.subscribe("home/vinyl/command/calibrate")
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

    sensors = {
        "artist": {"name": "Vinyl Artist", "icon": "mdi:account-music", "template": "{{ value_json.artist }}"},
        "title": {"name": "Vinyl Title", "icon": "mdi:music-circle", "template": "{{ value_json.title }}"},
        "album_art": {"name": "Vinyl Album Art", "icon": "mdi:image-album", "template": "{{ value_json.album_art }}"}
    }

    for sensor, details in sensors.items():
        payload = {
            "name": details["name"],
            "unique_id": f"vinyl_listener_{sensor}",
            "state_topic": "home/vinyl/now_playing",
            "value_template": details["template"],
            "icon": details["icon"],
            "device": device_info
        }
        client.publish(f"homeassistant/sensor/vinyl_listener/{sensor}/config", json.dumps(payload), retain=True)
     
    button_payload = {
        "name": "Calibrate Noise Floor",
        "unique_id": "vinyl_listener_calibrate_btn",
        "command_topic": "home/vinyl/command/calibrate",
        "icon": "mdi:tune",
        "device": device_info
    }
    client.publish("homeassistant/button/vinyl_listener/calibrate/config", json.dumps(button_payload), retain=True)

setup_mqtt_discovery()

def is_turntable_on():
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        return False
        
    url = f"http://supervisor/core/api/states/{TURNTABLE_ENTITY}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Host": "supervisor"}
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json().get("state") == "on"
    except Exception:
        pass
    return False

def scrobble_track(artist, title):
    """Sends track data to Last.fm."""
    if not LASTFM_ENABLED:
        return
        
    api_secret = config.get('lastfm_api_secret')
    username = config.get('lastfm_username')
    password = config.get('lastfm_password')
    
    if not all([LASTFM_KEY, api_secret, username, password]):
        print("⚠️ Last.fm is enabled, but credentials are missing in the configuration.")
        return

    try:
        network = pylast.LastFMNetwork(
            api_key=LASTFM_KEY,
            api_secret=api_secret,
            username=username,
            password_hash=pylast.md5(password)
        )
        network.scrobble(artist=artist, title=title, timestamp=int(time.time()))
        print("🎶 Successfully scrobbled to Last.fm!")
    except Exception as e:
        print(f"⚠️ Failed to scrobble to Last.fm: {e}")

def identify_acoustid(file_path):
    if not ACOUSTID_API_KEY:
        return None
    try:
        # acoustid.match yields tuples of (score, recording_id, title, artist)
        for score, recording_id, title, artist in acoustid.match(ACOUSTID_API_KEY, file_path):
            if title and artist:
                return {'title': title, 'artist': artist, 'source': 'AcoustID'}
    except acoustid.NoBackendError:
        print("⚠️ AcoustID failed: 'fpcalc' (chromaprint) is not installed in the system.")
    except Exception as e:
        print(f"⚠️ AcoustID lookup failed: {e}")
    return None

def identify_acrcloud(file_path):
    http_method = "POST"
    http_uri = "/v1/identify"
    data_type = "audio"
    signature_version = "1"
    timestamp = str(int(time.time()))

    string_to_sign = '\n'.join([http_method, http_uri, ACR_KEY, data_type, signature_version, timestamp])
    sign = base64.b64encode(hmac.new(ACR_SECRET.encode('ascii'), string_to_sign.encode('ascii'), digestmod=hashlib.sha1).digest()).decode('ascii')

    files = {'sample': open(file_path, 'rb')}
    data = {
        'access_key': ACR_KEY, 'sample_bytes': os.path.getsize(file_path),
        'timestamp': timestamp, 'signature': sign, 'data_type': data_type, "signature_version": signature_version
    }
    
    try:
        r = requests.post(f"https://{ACR_HOST}{http_uri}", files=files, data=data, timeout=10)
        return r.json()
    except Exception:
        return None

async def identify_hybrid(file_path):
    # 1. Try Local Shazam First (Free)
    try:
        out = await shazam.recognize(file_path)
        if out and 'track' in out:
            return {'title': out['track']['title'], 'artist': out['track']['subtitle'], 'source': 'Shazam'}
    except Exception:
        pass

    # 2. Try AcoustID Second (Free API)
    if ACOUSTID_API_KEY:
        print("Shazam failed, falling back to AcoustID...")
        out = identify_acoustid(file_path)
        if out:
            return out

    # 3. Try ACRCloud Last (Paid API Credits)
    if ACR_KEY and ACR_SECRET:
        print("AcoustID failed, falling back to ACRCloud...")
        out = identify_acrcloud(file_path)
        if out and out.get('status', {}).get('msg') == 'Success':
            metadata = out['metadata']['music'][0]
            title = metadata.get('title', 'Unknown')
            artist = metadata['artists'][0].get('name', 'Unknown') if metadata.get('artists') else 'Unknown'
            return {'title': title, 'artist': artist, 'source': 'ACRCloud'}
            
    return None

def get_album_art(artist, title):
    """Fetches album art from iTunes, with a fallback to Last.fm for underground metadata."""
    try:
        url = "https://itunes.apple.com/search"
        params = {"term": f"{artist} {title} Metal", "media": "music", "limit": 5}
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        if data.get('resultCount', 0) > 0:
            for result in data['results']:
                if artist.lower() in result.get('artistName', '').lower():
                    return result.get('artworkUrl100', '').replace('100x100bb', '600x600bb')
    except Exception:
        pass

    if LASTFM_KEY:
        try:
            print("🔍 iTunes matched nothing. Searching Last.fm API for artwork...")
            url = "http://ws.audioscrobbler.com/2.0/"
            params = {
                "method": "track.getInfo",
                "api_key": LASTFM_KEY,
                "artist": artist,
                "track": title,
                "format": "json"
            }
            r = requests.get(url, params=params, timeout=5)
            data = r.json()
            
            track_data = data.get('track', {})
            if track_data and 'album' in track_data and track_data['album']:
                images = track_data['album'].get('image', [])
                if images:
                    for img in reversed(images):
                        if img.get('#text'):
                            print("🎨 Successfully retrieved artwork via Last.fm API.")
                            return img.get('#text')
        except Exception as e:
            print(f"⚠️ Last.fm artwork fallback failed: {e}")
            
    return ""

# --- GRACEFUL SHUTDOWN HANDLER ---
def handle_shutdown(signum, frame):
    """Traps SIGTERM/SIGINT signals from the Supervisor for a clean exit."""
    print("\n🛑 SIGTERM received. Shutting down Vinyl Listener gracefully...")
    try:
        client.loop_stop()
        client.disconnect()
    except Exception:
        pass
    sys.exit(0)

def main_loop():
    global global_volume_threshold
    print("Vinyl Listener hybrid service started. Listening for turntable...")
    
    in_track_lock = False
    silence_seconds = 0
    next_retry_time = 0
    last_turntable_state = None
    failed_attempts = 0
    
    while True:
        turntable_on = is_turntable_on()
        
        if turntable_on != last_turntable_state:
            print(f"🎛️ Turntable switch ({TURNTABLE_ENTITY}) monitored state changed to: {'ON' if turntable_on else 'OFF'}")
            
            if turntable_on and AUTO_CALIBRATE:
                global_volume_threshold = calibrate_noise_floor()
                
            if not turntable_on and last_turntable_state is True:
                print("🛑 Turntable is OFF. Clearing MQTT track data.")
                clear_payload = {"title": "Idle", "artist": "Turntable", "album_art": IDLE_IMAGE}
                client.publish("home/vinyl/now_playing", json.dumps(clear_payload), retain=True)
                failed_attempts = 0

            last_turntable_state = turntable_on

        if not turntable_on:
            in_track_lock = False
            silence_seconds = 0
            time.sleep(5)
            continue
            
        volume = get_local_volume()
        
        if in_track_lock:
            if volume < global_volume_threshold:
                silence_seconds += 0.1
                if silence_seconds >= REQUIRED_SILENCE_SEC:
                    print(f"🎵 Track gap detected ({REQUIRED_SILENCE_SEC}s of silence). Arming for next song.")
                    in_track_lock = False
                    silence_seconds = 0
            else:
                silence_seconds = 0
        else:
            if volume >= global_volume_threshold:
                if time.time() < next_retry_time:
                    time.sleep(0.1)
                    continue
                    
                if failed_attempts == 0 and SAMPLE_DELAY > 0:
                    print(f"⏳ Track start detected. Letting the intro play for {SAMPLE_DELAY}s before sampling...")
                    time.sleep(SAMPLE_DELAY)
                    
                sample_file = "/share/debug_sample.wav" if DEBUG_MODE else "/tmp/sample.wav"
                
                print(f"🔊 Capturing fingerprint sample to {sample_file}...")
                process = subprocess.run(["arecord", "-D", "pulse", "-d", "8", "-f", "cd", sample_file], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                
                if process.returncode != 0:
                    continue
                    
                result = asyncio.run(identify_hybrid(sample_file))
                
                if result:
                    art = get_album_art(result['artist'], result['title'])
                    payload = {"title": result['title'], "artist": result['artist'], "album_art": art}
                    
                    print(f"🔥 NEW TRACK DETECTED via {result['source']}: {result['artist']} - {result['title']}")
                    client.publish("home/vinyl/now_playing", json.dumps(payload), retain=True)
                    
                    scrobble_track(result['artist'], result['title'])
                    
                    in_track_lock = True
                    silence_seconds = 0
                    failed_attempts = 0
                else:
                    failed_attempts += 1
                    if failed_attempts >= MAX_RETRIES:
                        print(f"❌ Failed to identify audio {MAX_RETRIES} times. Locking out until next track to save API credits.")
                        payload = {"title": "Unknown Track", "artist": "Unknown Artist", "album_art": IDLE_IMAGE}
                        client.publish("home/vinyl/now_playing", json.dumps(payload), retain=True)
                        
                        in_track_lock = True
                        silence_seconds = 0
                        failed_attempts = 0
                    else:
                        print(f"Audio detected but no metadata match found (Attempt {failed_attempts}/{MAX_RETRIES}). Cooling down 15s...")
                        next_retry_time = time.time() + 15
                    
                if not DEBUG_MODE and os.path.exists(sample_file):
                    os.remove(sample_file)
                    
        time.sleep(0.1)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    main_loop()
