# Vinyl Listener
Vinyl Listener for Home Assistant A high-precision vinyl identification add-on.

Features
Hybrid Identification: Attempts free local identification using Shazam first. Only falls back to ACRCloud if the track is not found, saving you API costs.

Silence Detection: Automatically arms itself after the gap between tracks, preventing unnecessary API spam.

Automatic Album Art: Fetches high-res metadata and artwork via the iTunes API.

Installation
Add this repository to the Repositories in Apps.

Install the add-on.

Configuration: Enter your ACRCloud API keys in the add-on configuration tab. (Optional: Identification works for free without them using Shazam).
