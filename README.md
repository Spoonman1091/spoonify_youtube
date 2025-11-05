# Spotify to YouTube Music Playlist Exporter

A Python script that exports your Spotify playlists to YouTube Music, automatically matching and adding songs.

## Features

- Export any Spotify playlist (public or private) to YouTube Music
- Automatic fallback to headless browser scraping if API access fails (works with playlists like "mint", "Top 50", etc.)
- Uses Playwright to render JavaScript and intercept network requests for reliable data extraction
- List all your Spotify playlists with the `--list` command
- Automatic song matching using track name and artist
- Progress tracking with detailed output
- Configurable playlist privacy settings
- Reports tracks that couldn't be found

## Prerequisites

- Python 3.7 or higher
- A Spotify account
- A YouTube/Google account with YouTube Music access
- Spotify Developer Application credentials

## Setup

### 1. Install Dependencies

```bash
python3 -m pip install -r requirements.txt
```

After installing Python packages, install Playwright browsers:

```bash
playwright install chromium
```

This downloads the Chromium browser that Playwright uses for web scraping when the Spotify API doesn't work.

### 2. Set Up Spotify API Credentials

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Log in with your Spotify account
3. Click "Create an App"
4. Fill in the app name and description
5. Once created, you'll see your **Client ID** and **Client Secret**
6. Click "Edit Settings" and add a Redirect URI: `http://localhost:8888/callback`

#### Option A: Config File (Recommended)

Create a `config.json` file in the same directory as the script:

```bash
cp config.example.json config.json
```

Then edit `config.json` with your credentials:

```json
{
  "spotify": {
    "client_id": "your_spotify_client_id_here",
    "client_secret": "your_spotify_client_secret_here",
    "redirect_uri": "http://localhost:8888/callback"
  },
  "youtube_music": {
    "headers_file": "headers_auth.json"
  }
}
```

#### Option B: Environment Variables

Alternatively, you can use environment variables:

```bash
export SPOTIFY_CLIENT_ID="your_client_id_here"
export SPOTIFY_CLIENT_SECRET="your_client_secret_here"
export SPOTIFY_REDIRECT_URI="http://localhost:8888/callback"
```

Or on Windows (PowerShell):

```powershell
$env:SPOTIFY_CLIENT_ID="your_client_id_here"
$env:SPOTIFY_CLIENT_SECRET="your_client_secret_here"
$env:SPOTIFY_REDIRECT_URI="http://localhost:8888/callback"
```

### 3. Set Up YouTube Music Authentication

You have two options for YouTube Music authentication:

#### Option A: Browser Headers (Recommended - No Google Cloud Setup Required)

```bash
ytmusicapi browser
```

Follow the instructions to extract authentication headers from your browser:
1. Open YouTube Music (music.youtube.com) in your browser and log in
2. Open Developer Tools (F12)
3. Go to the Network tab
4. Find a request to `music.youtube.com`
5. Copy the request headers as instructed
6. Paste them when prompted

This will create a `browser.json` file automatically. **No need to rename it** - the script will auto-detect it.

#### Option B: OAuth (Requires Google Cloud Project)

This method requires setting up a Google Cloud project and enabling the YouTube Data API v3:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable "YouTube Data API v3"
4. Create OAuth 2.0 credentials (Desktop app type)
5. Run:
```bash
ytmusicapi oauth
```
6. Enter your Google OAuth client ID and secret (NOT your Spotify credentials)

This will create an `oauth.json` file automatically. **No need to rename it** - the script will auto-detect it.

**Note**: The script automatically looks for `oauth.json` or `browser.json`. If you want to use a custom filename, specify it in your `config.json`:
```json
{
  "youtube_music": {
    "headers_file": "custom_filename.json"
  }
}
```

## Usage

### List Your Playlists

To see all your Spotify playlists and their IDs:

```bash
python3 spotify_to_youtube.py --list
```

This will display:
- Playlist name
- Playlist ID
- Number of tracks
- Owner
- Privacy status (Public/Private)
- Direct URL

### Basic Usage

Export a Spotify playlist (defaults to PRIVATE on YouTube Music):

```bash
python3 spotify_to_youtube.py "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
```

Or use just the playlist ID:

```bash
python3 spotify_to_youtube.py 37i9dQZF1DXcBWIGoYBM5M
```

### With Custom Privacy Settings

```bash
python3 spotify_to_youtube.py PLAYLIST_ID --privacy PUBLIC
python3 spotify_to_youtube.py PLAYLIST_ID --privacy UNLISTED
```

### Finding Your Spotify Playlist ID

**Method 1: Use the --list flag (Easiest)**
```bash
python3 spotify_to_youtube.py --list
```

**Method 2: Manually from Spotify**
1. Open Spotify and navigate to your playlist
2. Click the three dots (...) menu
3. Select "Share" → "Copy link to playlist"
4. The URL will look like: `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M`
5. You can use the full URL or just the ID part (`37i9dQZF1DXcBWIGoYBM5M`)

## How It Works

1. **Fetches Spotify Playlist**: Connects to Spotify API and retrieves all tracks from the specified playlist
2. **Searches YouTube Music**: For each track, searches YouTube Music using the track name and artist
3. **Matches Songs**: Finds the best match for each track (currently uses the first search result)
4. **Creates Playlist**: Creates a new playlist on YouTube Music with the same name
5. **Adds Tracks**: Adds all matched tracks to the new playlist

## Troubleshooting

### Spotify Authentication Errors

- Make sure your Client ID and Client Secret are correct
- Verify the Redirect URI in your Spotify app settings matches exactly: `http://localhost:8888/callback`
- On first run, a browser window will open for you to authorize the app

### YouTube Music Authentication Errors

- Make sure `headers_auth.json` (or `oauth.json`) exists in the same directory as the script
- If using browser headers, ensure you're logged into YouTube Music when extracting headers
- Headers may expire after a while; regenerate if needed

### Missing Tracks

Some tracks may not be found on YouTube Music because:
- They're not available in your region
- The track/artist name differs between platforms
- The track is a Spotify exclusive
- Search matching failed (rare)

The script will report which tracks couldn't be found at the end.

## Privacy Settings

- **PRIVATE**: Only you can see the playlist (default)
- **UNLISTED**: Anyone with the link can see the playlist
- **PUBLIC**: Anyone can find and see the playlist

## Limitations

- Local files in Spotify playlists are skipped
- Song matching is based on text search and may not always be 100% accurate
- YouTube Music API rate limits may apply for very large playlists

## Contributing

Feel free to submit issues or pull requests for improvements.

## License

MIT License - feel free to use and modify as needed.
