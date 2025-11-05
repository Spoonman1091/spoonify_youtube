#!/usr/bin/env python3
"""
Spotify to YouTube Music Playlist Exporter

This script exports a Spotify playlist to YouTube Music by:
1. Fetching tracks from a Spotify playlist
2. Searching for matching tracks on YouTube Music
3. Creating a new playlist on YouTube Music and adding the tracks
"""

import os
import sys
import json
import re
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from ytmusicapi import YTMusic
from typing import List, Dict, Optional
import argparse
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


class SpotifyToYouTubeMusic:
    def __init__(self, config_file='config.json'):
        """Initialize the Spotify and YouTube Music clients."""
        self.spotify = None
        self.ytmusic = None
        self.config = self.load_config(config_file)
        self.setup_spotify()
        self.setup_youtube_music()

    def load_config(self, config_file: str) -> Dict:
        """
        Load configuration from a JSON file or fall back to environment variables.

        Args:
            config_file: Path to the configuration file

        Returns:
            Dictionary containing configuration values
        """
        config = {}

        # Try to load from config file first
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                print(f"✓ Loaded configuration from {config_file}")
            except Exception as e:
                print(f"Warning: Failed to load config file '{config_file}': {e}")

        # Fall back to environment variables if config file values are missing
        if not config.get('spotify'):
            config['spotify'] = {}
        if not config['spotify'].get('client_id'):
            config['spotify']['client_id'] = os.getenv('SPOTIFY_CLIENT_ID')
        if not config['spotify'].get('client_secret'):
            config['spotify']['client_secret'] = os.getenv('SPOTIFY_CLIENT_SECRET')
        if not config['spotify'].get('redirect_uri'):
            config['spotify']['redirect_uri'] = os.getenv('SPOTIFY_REDIRECT_URI', 'http://localhost:8888/callback')

        if not config.get('youtube_music'):
            config['youtube_music'] = {}

        return config

    def setup_spotify(self):
        """Set up Spotify authentication using config file or environment variables."""
        client_id = self.config['spotify'].get('client_id')
        client_secret = self.config['spotify'].get('client_secret')
        redirect_uri = self.config['spotify'].get('redirect_uri', 'http://localhost:8888/callback')

        if not client_id or not client_secret:
            print("ERROR: Spotify credentials not found!")
            print("Please provide credentials in one of the following ways:")
            print("\n1. Create a config.json file (recommended):")
            print("   {")
            print('     "spotify": {')
            print('       "client_id": "your_client_id_here",')
            print('       "client_secret": "your_client_secret_here",')
            print('       "redirect_uri": "http://localhost:8888/callback"')
            print("     }")
            print("   }")
            print("\n2. Set environment variables:")
            print("   - SPOTIFY_CLIENT_ID")
            print("   - SPOTIFY_CLIENT_SECRET")
            print("   - SPOTIFY_REDIRECT_URI (optional)")
            print("\nYou can get these credentials from: https://developer.spotify.com/dashboard")
            sys.exit(1)

        scope = "playlist-read-private playlist-read-collaborative"

        try:
            self.spotify = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope
            ))
            print("✓ Spotify authentication successful")
        except Exception as e:
            print(f"ERROR: Failed to authenticate with Spotify: {e}")
            sys.exit(1)

    def setup_youtube_music(self):
        """Set up YouTube Music authentication using headers file."""
        # Check config file first
        configured_file = self.config['youtube_music'].get('headers_file')

        # Default files to check in order of preference
        default_files = ['oauth.json', 'browser.json', 'headers_auth.json']

        headers_file = None

        # If a specific file is configured, use only that
        if configured_file:
            if os.path.exists(configured_file):
                headers_file = configured_file
        else:
            # Otherwise check default files
            for file in default_files:
                if os.path.exists(file):
                    headers_file = file
                    break

        if not headers_file:
            print("\nERROR: YouTube Music authentication file not found!")
            print("\nTo set up YouTube Music authentication, choose one of these methods:")
            print("\nOption 1 - OAuth (requires Google Cloud project):")
            print("  1. Run: ytmusicapi oauth")
            print("  2. Follow instructions to authenticate")
            print("  3. This creates 'oauth.json'")
            print("\nOption 2 - Browser headers (recommended, no setup needed):")
            print("  1. Run: ytmusicapi browser")
            print("  2. Follow instructions to extract headers from your browser")
            print("  3. This creates 'browser.json'")
            if configured_file:
                print(f"\nNote: You have '{configured_file}' configured in config.json")
                print(f"      but this file doesn't exist.")
            sys.exit(1)

        try:
            self.ytmusic = YTMusic(headers_file)
            print("✓ YouTube Music authentication successful")
        except Exception as e:
            print(f"ERROR: Failed to authenticate with YouTube Music: {e}")
            sys.exit(1)

    def list_user_playlists(self):
        """
        List all playlists for the authenticated user.
        """
        print(f"\n{'='*60}")
        print("Your Spotify Playlists")
        print(f"{'='*60}\n")

        try:
            # Get current user info
            user = self.spotify.current_user()
            print(f"Logged in as: {user['display_name']} ({user['id']})\n")

            # Fetch all playlists
            playlists = []
            results = self.spotify.current_user_playlists(limit=50)

            while results:
                playlists.extend(results['items'])
                results = self.spotify.next(results) if results['next'] else None

            if not playlists:
                print("No playlists found.")
                return

            print(f"Found {len(playlists)} playlist(s):\n")

            for idx, playlist in enumerate(playlists, 1):
                name = playlist['name']
                playlist_id = playlist['id']
                track_count = playlist['tracks']['total']
                owner = playlist['owner']['display_name']
                is_public = playlist.get('public', False)
                visibility = "Public" if is_public else "Private"

                print(f"{idx}. {name}")
                print(f"   ID: {playlist_id}")
                print(f"   Tracks: {track_count} | Owner: {owner} | {visibility}")
                print(f"   URL: https://open.spotify.com/playlist/{playlist_id}")
                print()

        except Exception as e:
            print(f"ERROR: Failed to fetch playlists: {e}")
            sys.exit(1)

    def get_spotify_playlist_from_web(self, playlist_url: str) -> Dict:
        """
        Fetch a Spotify playlist from the web page using Playwright (fallback when API fails).

        Args:
            playlist_url: Spotify playlist URL

        Returns:
            Dictionary containing playlist info and tracks
        """
        try:
            print("  (Using headless browser to render page)")

            playlist_data = None
            captured_data = []

            with sync_playwright() as p:
                # Launch browser
                print("    Launching browser...")
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = context.new_page()

                # Intercept API responses to capture playlist data
                def handle_response(response):
                    url = response.url
                    # Look for Spotify API calls
                    if any(domain in url for domain in ['api.spotify.com', 'spclient', 'api-partner']):
                        try:
                            if response.status == 200:
                                data = response.json()
                                if data and isinstance(data, dict):
                                    captured_data.append({'url': url, 'data': data})
                        except:
                            pass

                page.on('response', handle_response)

                # Navigate to playlist
                print(f"    Loading {playlist_url}")
                try:
                    page.goto(playlist_url, wait_until='networkidle', timeout=30000)
                    print("    Page loaded, waiting for content...")

                    # Wait for playlist content to appear
                    page.wait_for_selector('[data-testid="playlist-page"]', timeout=10000)
                    print("    Playlist content detected")

                    # Give it a moment for all API calls to complete
                    time.sleep(2)

                except PlaywrightTimeout:
                    print("    Warning: Timeout waiting for playlist, continuing anyway...")

                # Try to extract data from captured API responses
                for item in captured_data:
                    data = item.get('data', {})

                    # Look for different possible structures
                    # Structure: data.data.playlistV2
                    if 'data' in data and 'playlistV2' in data['data']:
                        playlist_info = data['data']['playlistV2']

                        # Check if this has actual content (not just permissions/metadata)
                        if 'content' in playlist_info and 'items' in playlist_info['content']:
                            if len(playlist_info['content']['items']) > 0:
                                playlist_data = {
                                    'playlist': playlist_info,
                                    'source': 'api_intercept'
                                }
                                print(f"    Extracted playlist data successfully")
                                break
                        # If no content but has name/description, keep looking for content
                        elif 'name' in playlist_info and not playlist_data:
                            playlist_data = {
                                'playlist': playlist_info,
                                'source': 'api_intercept'
                            }
                    elif 'playlistV2' in data:
                        playlist_info = data['playlistV2']
                        if 'content' in playlist_info:
                            playlist_data = {
                                'playlist': playlist_info,
                                'source': 'api_intercept'
                            }
                            break

                # If no API data captured, try to extract from page content
                if not playlist_data:
                    print("    No API data captured, attempting DOM extraction...")
                    page_content = page.content()

                    # Try to find embedded JSON data in the rendered page
                    soup = BeautifulSoup(page_content, 'html.parser')
                    scripts = soup.find_all('script')

                    for script in scripts:
                        if script.string and 'playlistV2' in script.string:
                            try:
                                # Try to extract JSON
                                json_match = re.search(r'\{[^{]*"playlistV2"[^}]*\{.*?\}\}', script.string, re.DOTALL)
                                if json_match:
                                    data = json.loads(json_match.group())
                                    playlist_data = {'playlist': data, 'source': 'dom'}
                                    break
                            except:
                                continue

                browser.close()

            if not playlist_data:
                raise Exception("Could not extract playlist data from page")

            # Navigate the data structure to find tracks
            tracks = []
            playlist_name = 'Unknown Playlist'
            playlist_description = ''

            # Try different data structure paths
            try:
                # Path 1: Intercepted API response with playlistV2
                if 'playlist' in playlist_data and playlist_data.get('source') == 'api_intercept':
                    playlist_info = playlist_data['playlist']

                    if 'name' in playlist_info:
                        playlist_name = playlist_info['name']
                    if 'description' in playlist_info:
                        playlist_description = playlist_info['description']

                    # Get tracks from content.items
                    if 'content' in playlist_info and 'items' in playlist_info['content']:
                        for item in playlist_info['content']['items']:
                            try:
                                # Navigate to track data
                                track_data = None
                                if 'itemV2' in item:
                                    track_data = item['itemV2'].get('data', {})
                                elif 'track' in item:
                                    track_data = item['track']

                                if track_data and track_data.get('name'):
                                    # Extract artists
                                    artists = []
                                    if 'artists' in track_data and 'items' in track_data['artists']:
                                        for artist in track_data['artists']['items']:
                                            artist_name = artist.get('profile', {}).get('name') or artist.get('name', '')
                                            if artist_name:
                                                artists.append(artist_name)

                                    if artists:
                                        tracks.append({
                                            'name': track_data['name'],
                                            'artists': artists,
                                            'album': track_data.get('albumOfTrack', {}).get('name', ''),
                                            'duration_ms': track_data.get('trackDuration', {}).get('totalMilliseconds', 0)
                                        })
                            except Exception as e:
                                continue

                # Path 2: entities.items[playlist_id].content.items (legacy structure)
                elif 'entities' in playlist_data and 'items' in playlist_data['entities']:
                    items_obj = playlist_data['entities']['items']

                    # Find the playlist object
                    for key, value in items_obj.items():
                        if 'playlist' in key.lower() and isinstance(value, dict):
                            if 'name' in value:
                                playlist_name = value['name']
                            if 'description' in value:
                                playlist_description = value['description']

                            # Get tracks
                            if 'content' in value and 'items' in value['content']:
                                for item in value['content']['items']:
                                    try:
                                        # Navigate to track data
                                        track_data = item.get('itemV2', {}).get('data', {})
                                        if not track_data:
                                            track_data = item.get('track', {})

                                        if track_data and track_data.get('name'):
                                            # Extract artists
                                            artists = []
                                            if 'artists' in track_data:
                                                artists_data = track_data['artists']
                                                if isinstance(artists_data, dict) and 'items' in artists_data:
                                                    artists = [a.get('profile', {}).get('name', '') or a.get('name', '')
                                                             for a in artists_data['items']]
                                                elif isinstance(artists_data, list):
                                                    artists = [a.get('name', '') for a in artists_data]

                                            if artists:
                                                tracks.append({
                                                    'name': track_data['name'],
                                                    'artists': artists,
                                                    'album': track_data.get('albumOfTrack', {}).get('name', ''),
                                                    'duration_ms': track_data.get('duration', {}).get('totalMilliseconds', 0)
                                                })
                                    except Exception as e:
                                        continue
                            break

            except Exception as e:
                pass

            if not tracks:
                raise Exception("Could not extract tracks from playlist data")

            return {
                'name': playlist_name,
                'description': playlist_description,
                'total_tracks': len(tracks),
                'tracks': tracks
            }

        except Exception as e:
            raise Exception(f"Failed to fetch playlist from web: {e}")

    def get_spotify_playlist(self, playlist_id: str) -> Dict:
        """
        Fetch a Spotify playlist and its tracks.
        Tries API first, falls back to web scraping if API fails.

        Args:
            playlist_id: Spotify playlist ID or URL

        Returns:
            Dictionary containing playlist info and tracks
        """
        # Extract playlist ID if full URL is provided
        playlist_url = playlist_id
        if 'spotify.com/playlist/' in playlist_id:
            playlist_id = playlist_id.split('playlist/')[1].split('?')[0]
            playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"
        else:
            playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"

        # Try API first
        try:
            playlist = self.spotify.playlist(playlist_id)

            tracks = []
            results = playlist['tracks']

            while results:
                for item in results['items']:
                    if item['track']:  # Check if track exists (not a local file)
                        track = item['track']
                        tracks.append({
                            'name': track['name'],
                            'artists': [artist['name'] for artist in track['artists']],
                            'album': track['album']['name'],
                            'duration_ms': track['duration_ms']
                        })

                # Get next page of results if available
                results = self.spotify.next(results) if results['next'] else None

            return {
                'name': playlist['name'],
                'description': playlist['description'],
                'total_tracks': len(tracks),
                'tracks': tracks
            }
        except Exception as api_error:
            # If API fails, try web scraping
            print(f"  API access failed ({api_error})")
            print(f"  Attempting to fetch from web...")

            try:
                return self.get_spotify_playlist_from_web(playlist_url)
            except Exception as web_error:
                print(f"ERROR: Failed to fetch Spotify playlist via API and web")
                print(f"  API error: {api_error}")
                print(f"  Web error: {web_error}")
                sys.exit(1)

    def search_youtube_music_track(self, track: Dict) -> Optional[str]:
        """
        Search for a track on YouTube Music.

        Args:
            track: Dictionary containing track info (name, artists, etc.)

        Returns:
            YouTube Music video ID if found, None otherwise
        """
        try:
            # Create search query
            artist_names = ', '.join(track['artists'])
            query = f"{track['name']} {artist_names}"

            # Search on YouTube Music
            search_results = self.ytmusic.search(query, filter='songs', limit=5)

            if not search_results:
                return None

            # Return the first result's video ID
            # TODO: Could implement more sophisticated matching based on duration, etc.
            return search_results[0]['videoId']

        except Exception as e:
            print(f"  Warning: Failed to search for track '{track['name']}': {e}")
            return None

    def create_youtube_playlist(self, playlist_name: str, description: str,
                               video_ids: List[str], privacy: str = 'PRIVATE') -> str:
        """
        Create a new YouTube Music playlist and add tracks.

        Args:
            playlist_name: Name of the new playlist
            description: Playlist description
            video_ids: List of YouTube Music video IDs to add
            privacy: Privacy setting (PRIVATE, PUBLIC, or UNLISTED)

        Returns:
            Playlist ID of the created playlist
        """
        try:
            # Create the playlist
            playlist_id = self.ytmusic.create_playlist(
                title=playlist_name,
                description=description,
                privacy_status=privacy
            )

            print(f"\n✓ Created YouTube Music playlist: {playlist_name}")

            # Add tracks in batches (YouTube Music API has limits)
            if video_ids:
                batch_size = 50
                for i in range(0, len(video_ids), batch_size):
                    batch = video_ids[i:i + batch_size]
                    self.ytmusic.add_playlist_items(playlist_id, batch)
                    print(f"  Added {len(batch)} tracks (batch {i//batch_size + 1})")

            return playlist_id

        except Exception as e:
            print(f"ERROR: Failed to create YouTube Music playlist: {e}")
            raise

    def export_playlist(self, spotify_playlist_id: str, privacy: str = 'PRIVATE'):
        """
        Main function to export a Spotify playlist to YouTube Music.

        Args:
            spotify_playlist_id: Spotify playlist ID or URL
            privacy: Privacy setting for the YouTube Music playlist
        """
        print(f"\n{'='*60}")
        print("Spotify to YouTube Music Playlist Export")
        print(f"{'='*60}\n")

        # Fetch Spotify playlist
        print("Fetching Spotify playlist...")
        playlist = self.get_spotify_playlist(spotify_playlist_id)
        print(f"✓ Found playlist: '{playlist['name']}' ({playlist['total_tracks']} tracks)")

        # Search for tracks on YouTube Music
        print(f"\nSearching for tracks on YouTube Music...")
        video_ids = []
        not_found = []

        for idx, track in enumerate(playlist['tracks'], 1):
            artist_names = ', '.join(track['artists'])
            print(f"  [{idx}/{playlist['total_tracks']}] {track['name']} - {artist_names}...", end=' ')

            video_id = self.search_youtube_music_track(track)

            if video_id:
                video_ids.append(video_id)
                print("✓")
            else:
                not_found.append(f"{track['name']} - {artist_names}")
                print("✗ Not found")

        print(f"\n✓ Found {len(video_ids)}/{playlist['total_tracks']} tracks on YouTube Music")

        if not_found:
            print(f"\nTracks not found ({len(not_found)}):")
            for track in not_found[:10]:  # Show first 10
                print(f"  - {track}")
            if len(not_found) > 10:
                print(f"  ... and {len(not_found) - 10} more")

        # Create YouTube Music playlist
        if video_ids:
            print(f"\nCreating YouTube Music playlist...")
            description = f"Imported from Spotify playlist: {playlist['name']}"
            if playlist['description']:
                description += f"\n\n{playlist['description']}"

            playlist_id = self.create_youtube_playlist(
                playlist_name=playlist['name'],
                description=description,
                video_ids=video_ids,
                privacy=privacy
            )

            print(f"\n{'='*60}")
            print("✓ Export complete!")
            print(f"{'='*60}")
            print(f"Playlist URL: https://music.youtube.com/playlist?list={playlist_id}")
            print(f"Tracks added: {len(video_ids)}/{playlist['total_tracks']}")
        else:
            print("\n✗ No tracks were found on YouTube Music. Playlist not created.")


def main():
    parser = argparse.ArgumentParser(
        description='Export a Spotify playlist to YouTube Music',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s --list
  %(prog)s https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
  %(prog)s 37i9dQZF1DXcBWIGoYBM5M --privacy PUBLIC

Environment Variables:
  SPOTIFY_CLIENT_ID      Your Spotify application client ID
  SPOTIFY_CLIENT_SECRET  Your Spotify application client secret
  SPOTIFY_REDIRECT_URI   OAuth redirect URI (default: http://localhost:8888/callback)
        '''
    )

    parser.add_argument(
        'playlist_id',
        nargs='?',
        help='Spotify playlist ID or URL'
    )

    parser.add_argument(
        '--list',
        action='store_true',
        help='List all your Spotify playlists and their IDs'
    )

    parser.add_argument(
        '--privacy',
        choices=['PRIVATE', 'PUBLIC', 'UNLISTED'],
        default='PRIVATE',
        help='YouTube Music playlist privacy setting (default: PRIVATE)'
    )

    args = parser.parse_args()

    try:
        exporter = SpotifyToYouTubeMusic()

        if args.list:
            exporter.list_user_playlists()
        elif args.playlist_id:
            exporter.export_playlist(args.playlist_id, args.privacy)
        else:
            parser.print_help()
            print("\nERROR: Please provide a playlist ID or use --list to see your playlists")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\nExport cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
