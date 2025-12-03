# Spotify to YouTube Music Playlist Exporter

A Python script that exports your Spotify playlists to YouTube Music, automatically matching and adding songs.

## Features

- Export any Spotify playlist (public or private) to YouTube Music
- **Update existing YouTube Music playlists** to match your Spotify playlists
- Automatic backup before updating (safety net if something goes wrong)
- Incremental updates: only adds new songs and removes deleted ones
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

After installing Python packages, install Patchright browsers:

```bash
patchright install chromium
```

This downloads the Chromium browser that Patchright uses for:
- Web scraping when the Spotify API doesn't work
- Automated YouTube Music authentication setup

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

You have three options for YouTube Music authentication:

#### Option A: Automated Setup (Easiest - Recommended)

Simply run:

```bash
python3 spotify_to_youtube.py --setup-youtube
```

**What happens:**
1. Opens a browser window to YouTube Music
2. You log in to your Google/YouTube account
3. Script automatically captures authentication headers
4. Saves to `browser.json` and verifies it works
5. Done! No manual copying/pasting required

This uses Patchright to avoid bot detection and automatically extract the required authentication headers.

#### Option B: Manual Browser Headers (No Google Cloud Setup Required)

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

This will create a `browser.json` file automatically.

#### Option C: OAuth (Requires Google Cloud Project)

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

This will create an `oauth.json` file automatically.

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

**List your Spotify playlists:**

```bash
python3 spotify_to_youtube.py --list-spotify
```

This will display:
- Playlist name
- Playlist ID
- Number of tracks
- Owner
- Privacy status (Public/Private)
- Direct URL

**List your YouTube Music playlists:**

```bash
python3 spotify_to_youtube.py --list-youtube
```

This will display:
- Playlist name
- Playlist ID (needed for `--update`)
- Number of tracks
- Direct URL

### Create a New Playlist

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

### Update an Existing Playlist

To update an existing YouTube Music playlist to match your Spotify playlist:

```bash
python3 spotify_to_youtube.py SPOTIFY_PLAYLIST_ID --update YOUTUBE_MUSIC_PLAYLIST_ID
```

**How it works:**
1. Fetches the current YouTube Music playlist
2. Creates a backup (saved to `backups/` directory with timestamp)
3. Compares with the Spotify playlist to find differences
4. Removes songs that are no longer in Spotify
5. Adds new songs from Spotify that aren't in YouTube Music
6. Shows a summary of changes

**Skip backup (not recommended):**
```bash
python3 spotify_to_youtube.py SPOTIFY_ID --update YT_PLAYLIST_ID --no-backup
```

**Finding your YouTube Music playlist ID:**

**Method 1: Use the --list-youtube flag (Easiest)**
```bash
python3 spotify_to_youtube.py --list-youtube
```

**Method 2: Manually from YouTube Music**
1. Open the playlist in YouTube Music
2. The URL will look like: `https://music.youtube.com/playlist?list=PLxxxxxxxxxxxxxx`
3. Copy the part after `list=` (e.g., `PLxxxxxxxxxxxxxx`)

### Finding Your Spotify Playlist ID

**Method 1: Use the --list-spotify flag (Easiest)**
```bash
python3 spotify_to_youtube.py --list-spotify
```

**Method 2: Manually from Spotify**
1. Open Spotify and navigate to your playlist
2. Click the three dots (...) menu
3. Select "Share" → "Copy link to playlist"
4. The URL will look like: `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M`
5. You can use the full URL or just the ID part (`37i9dQZF1DXcBWIGoYBM5M`)

## How It Works

### Creating New Playlists

1. **Fetches Spotify Playlist**: Connects to Spotify API and retrieves all tracks from the specified playlist
2. **Searches YouTube Music**: For each track, searches YouTube Music using the track name and artist
3. **Matches Songs**: Finds the best match for each track (currently uses the first search result)
4. **Creates Playlist**: Creates a new playlist on YouTube Music with the same name
5. **Adds Tracks**: Adds all matched tracks to the new playlist

### Updating Existing Playlists

1. **Fetches Both Playlists**: Gets the current state of both Spotify and YouTube Music playlists
2. **Creates Backup**: Saves the current YouTube Music playlist to `backups/` directory (unless `--no-backup` is used)
3. **Compares Playlists**: Intelligently compares track names and artists to find differences
4. **Removes Old Tracks**: Deletes songs from YouTube Music that are no longer in the Spotify playlist
5. **Adds New Tracks**: Searches for and adds new songs from Spotify that aren't in YouTube Music yet
6. **Reports Results**: Shows summary of changes and backup location

**Backup files** are stored in the `backups/` directory with the format:
```
playlist_backup_{playlist_name}_{playlist_id}_{timestamp}.json
```

These backups can be used to restore your playlist if something goes wrong.

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
