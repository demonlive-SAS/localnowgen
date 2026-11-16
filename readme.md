## ⭐ LOCALNOW CHANNELS WITH WORKING EPG

- M3U Playlist URL:
[https://www.apsattv.com/localnow.m3u](https://www.apsattv.com/localnow.m3u)

- EPG XML URL:
[https://raw.githubusercontent.com/BuddyChewChew/localnow-playlist-generator/refs/heads/main/epg.xml](https://raw.githubusercontent.com/BuddyChewChew/localnow-playlist-generator/refs/heads/main/epg.xml)


![Screenshot](https://github.com/BuddyChewChew/localnow-playlist-generator/blob/main/Screenshot%202025-04-11%20012429.jpg)

About 95% Working Channels and Epg. Some channels listed don't work. Playlist used from: https://apsattv.com/streams.html


## How it works

A GitHub Actions workflow runs every 4 hours (at minute 45 UTC) and:

1. `generate_playlist.py` fetches the upstream Local Now playlist, adds a `tvg-name` to every channel, sets every `group-title` to `Fast Local Now`, removes duplicate channels, sorts by `tvg-name`, and writes `localnow.m3u`.
2. `generate_epg.py` fetches the Local Now guide data and writes `epg.xml` (XMLTV).

Run locally with Python 3.10+ (`pip install -r requirements.txt`, then `python generate_playlist.py` and `python generate_epg.py`). `generate_playlist.py --input file.m3u` reads a local playlist instead of fetching one.
