# Vinyl Listener
Vinyl Listener for Home Assistant A high-precision vinyl identification add-on.

Features
Hybrid Identification: Attempts free local identification using Shazam first. Only falls back to ACRCloud if the track is not found, saving you API calls. You get 100 calls a day for the free level of ACRCloud.

Silence Detection: Automatically arms itself after the gap between tracks, preventing unnecessary API spam.

Automatic Album Art: Fetches high-res metadata and artwork via the iTunes API.

Installation
Add this repository to the Repositories in Apps.

Install the add-on.

# Configuration: 

Enter your MQTT details.

Select your audio input device and output device.

Optional - Enter your ACRCloud API keys in the add-on configuration tab. (Identification works for free without them using Shazam).

Upon launch the add-on will create three sensors : 

sensor.vinyl_listener_vinyl_album_art

sensor.vinyl_listener_vinyl_artist

sensor.vinyl_listener_vinyl_title


Recommended hardware to interface is a Behringer UCA222 USB Audio Interface

Link : https://www.amazon.co.uk/dp/B0023BYDHK?ref=ppx_yo2ov_dt_b_fed_asin_title&th=1

Add-on will react to a switch - in my instance it's the turntable power. This prevents it from running all the time for no reason.

You can set the silence gap also (default 2s)
