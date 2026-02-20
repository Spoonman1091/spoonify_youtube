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

# Get the directory where this script is located (for running from any directory)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from ytmusicapi import YTMusic
from typing import List, Dict, Optional, Tuple
import argparse
from bs4 import BeautifulSoup
try:
    from patchright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class EmailNotifier:
    def __init__(self, config: Dict):
        """Initialize email notifier with configuration."""
        self.enabled = config.get('enabled', False)
        self.smtp_server = config.get('smtp_server', 'smtp.gmail.com')
        self.smtp_port = config.get('smtp_port', 587)
        self.sender_email = config.get('sender_email', '')
        self.sender_password = config.get('sender_password', '')
        self.recipient_email = config.get('recipient_email', '')
        self.use_tls = config.get('use_tls', True)

    def send_email(self, subject: str, body: str, is_html: bool = False):
        """
        Send an email notification.

        Args:
            subject: Email subject line
            body: Email body content
            is_html: Whether the body is HTML formatted
        """
        if not self.enabled:
            return

        if not all([self.sender_email, self.sender_password, self.recipient_email]):
            print("Warning: Email is enabled but credentials are missing. Skipping email notification.")
            return

        try:
            message = MIMEMultipart('alternative')
            message['From'] = self.sender_email
            message['To'] = self.recipient_email
            message['Subject'] = subject

            if is_html:
                message.attach(MIMEText(body, 'html'))
            else:
                message.attach(MIMEText(body, 'plain'))

            # Support both SMTP with STARTTLS (port 587) and SMTP_SSL (port 465)
            if self.smtp_port == 465:
                # Use SMTP_SSL for port 465
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=30) as server:
                    server.login(self.sender_email, self.sender_password)
                    server.send_message(message)
            else:
                # Use SMTP with STARTTLS for port 587
                with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30) as server:
                    if self.use_tls:
                        server.starttls()
                    server.login(self.sender_email, self.sender_password)
                    server.send_message(message)

            print(f"  Email notification sent to {self.recipient_email}")

        except Exception as e:
            print(f"  Warning: Failed to send email notification: {e}")

    def send_export_complete(self, playlist_name: str, total_tracks: int, found_tracks: int,
                           added_tracks: List[str], not_found_tracks: List[str], playlist_url: str = None):
        """Send notification when export completes."""
        subject = f"Playlist Export Complete: {playlist_name}"
        success_rate = (found_tracks / total_tracks * 100) if total_tracks > 0 else 0

        body = f"""
Spotify to YouTube Music Export Complete
=========================================

Playlist: {playlist_name}
Total Tracks: {total_tracks}
Tracks Added: {len(added_tracks)} ({success_rate:.1f}%)
Tracks Not Found: {len(not_found_tracks)}
Completed At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        if playlist_url:
            body += f"\nPlaylist URL: {playlist_url}\n"

        if added_tracks:
            body += f"\n{'='*60}\n"
            body += f"Tracks Added ({len(added_tracks)}):\n"
            body += f"{'='*60}\n"
            for track in added_tracks:
                body += f"  ✓ {track}\n"

        if not_found_tracks:
            body += f"\n{'='*60}\n"
            body += f"Tracks Not Found ({len(not_found_tracks)}):\n"
            body += f"{'='*60}\n"
            for track in not_found_tracks:
                body += f"  ✗ {track}\n"

        self.send_email(subject, body)

    def send_update_complete(self, playlist_name: str, added_track_names: List[str],
                           removed_track_names: List[str], not_found_tracks: List[str],
                           final_count: int, backup_path: str = None):
        """Send notification when playlist update completes."""
        subject = f"Playlist Update Complete: {playlist_name}"
        body = f"""
YouTube Music Playlist Update Complete
=======================================

Playlist: {playlist_name}
Tracks Added: {len(added_track_names)}
Tracks Removed: {len(removed_track_names)}
Tracks Not Found: {len(not_found_tracks)}
Final Track Count: {final_count}
Completed At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        if backup_path:
            body += f"\nBackup Saved To: {backup_path}\n"

        if added_track_names:
            body += f"\n{'='*60}\n"
            body += f"Tracks Added ({len(added_track_names)}):\n"
            body += f"{'='*60}\n"
            for track in added_track_names:
                body += f"  ✓ {track}\n"

        if removed_track_names:
            body += f"\n{'='*60}\n"
            body += f"Tracks Removed ({len(removed_track_names)}):\n"
            body += f"{'='*60}\n"
            for track in removed_track_names:
                body += f"  - {track}\n"

        if not_found_tracks:
            body += f"\n{'='*60}\n"
            body += f"Tracks Not Found ({len(not_found_tracks)}):\n"
            body += f"{'='*60}\n"
            for track in not_found_tracks:
                body += f"  ✗ {track}\n"

        self.send_email(subject, body)

    def send_error(self, operation: str, error_message: str):
        """Send notification when an error occurs."""
        subject = f"Error in {operation}"
        body = f"""
Spotify to YouTube Music - Error Occurred
==========================================

Operation: {operation}
Error Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Error Details:
{error_message}

Please check the logs for more information.
"""
        self.send_email(subject, body)


class SpotifyToYouTubeMusic:
    def __init__(self, config_file='config.json', skip_youtube_auth=False, disable_email=False):
        """Initialize the Spotify and YouTube Music clients."""
        self.spotify = None
        self.ytmusic = None
        # Resolve config file path relative to script directory
        if not os.path.isabs(config_file):
            config_file = os.path.join(SCRIPT_DIR, config_file)
        self.config = self.load_config(config_file)

        # Initialize email notifier
        email_config = self.config.get('email', {})
        if disable_email:
            email_config['enabled'] = False
        self.email_notifier = EmailNotifier(email_config)

        self.setup_spotify()
        if not skip_youtube_auth:
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
            # Resolve relative paths to script directory
            if not os.path.isabs(configured_file):
                configured_file = os.path.join(SCRIPT_DIR, configured_file)
            if os.path.exists(configured_file):
                headers_file = configured_file
        else:
            # Otherwise check default files in script directory
            for file in default_files:
                file_path = os.path.join(SCRIPT_DIR, file)
                if os.path.exists(file_path):
                    headers_file = file_path
                    break

        if not headers_file:
            print("\nERROR: YouTube Music authentication file not found!")
            print("\nTo set up YouTube Music authentication, choose one of these methods:")
            print("\nOption 1 - Automated setup (easiest):")
            print("  Run: python3 spotify_to_youtube.py --setup-youtube")
            print("\nOption 2 - OAuth (requires Google Cloud project):")
            print("  1. Run: ytmusicapi oauth")
            print("  2. Follow instructions to authenticate")
            print("  3. This creates 'oauth.json'")
            print("\nOption 3 - Manual browser headers:")
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

    def setup_youtube_auth_interactive(self, output_file: str = 'browser.json'):
        """
        Automatically extract YouTube Music authentication headers using browser.

        Args:
            output_file: Path to save the authentication headers
        """
        # Resolve output file path relative to script directory
        if not os.path.isabs(output_file):
            output_file = os.path.join(SCRIPT_DIR, output_file)

        print(f"\n{'='*60}")
        print("YouTube Music Authentication Setup")
        print(f"{'='*60}\n")

        print("This will open a browser window to YouTube Music.")
        print("Please log in to your YouTube/Google account when prompted.\n")
        print("Press Enter to continue...")
        input()

        captured_headers = None
        user_data_dir = os.path.join(SCRIPT_DIR, '.browser_profile')

        try:
            with sync_playwright() as p:
                print("\nLaunching browser with stealth settings...")

                # Launch with arguments to avoid detection
                browser = p.chromium.launch(
                    headless=False,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-web-security',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--disable-setuid-sandbox',
                        '--disable-accelerated-2d-canvas',
                        '--disable-gpu'
                    ]
                )

                # Create context with persistent storage and realistic settings
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US',
                    timezone_id='America/New_York',
                    permissions=['geolocation'],
                    storage_state=None if not os.path.exists(user_data_dir + '/state.json') else user_data_dir + '/state.json'
                )

                # Add stealth scripts to avoid detection
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });

                    window.navigator.chrome = {
                        runtime: {}
                    };

                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });

                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });
                """)

                page = context.new_page()

                # Intercept requests to capture headers
                request_count = 0
                post_count = 0
                def handle_request(request):
                    nonlocal captured_headers, request_count, post_count
                    url = request.url

                    # Log all music.youtube.com requests for debugging
                    if 'music.youtube.com' in url:
                        request_count += 1
                        if request_count <= 5:  # Show first 5 requests
                            print(f"  [Request {request_count}] {request.method} {url[:80]}...")

                    # Look for authenticated POST requests to YouTube Music API
                    if 'music.youtube.com' in url and request.method == 'POST':
                        post_count += 1
                        headers = request.headers

                        # Debug: Show POST request details
                        if post_count <= 3 and captured_headers is None:
                            print(f"\n  [POST {post_count}] URL: {url[:70]}...")
                            print(f"  [POST {post_count}] Headers present: {', '.join(sorted(headers.keys())[:10])}")

                            # Check for authentication headers
                            has_cookie = any(k.lower() == 'cookie' for k in headers.keys())
                            has_auth = any(k.lower() == 'authorization' for k in headers.keys())
                            print(f"  [POST {post_count}] Has cookie: {has_cookie}, Has authorization: {has_auth}")

                        # Check if this request has authentication (cookie OR authorization header)
                        has_auth = False
                        for key in headers.keys():
                            if key.lower() in ['cookie', 'authorization']:
                                has_auth = True
                                break

                        # Capture headers from youtubei API requests that have authentication
                        if has_auth and 'youtubei' in url and captured_headers is None:
                            print(f"\n✓ Captured authentication headers from: {url[:60]}...")
                            captured_headers = dict(headers)

                page.on('request', handle_request)

                print("Opening YouTube Music...")
                page.goto('https://music.youtube.com', wait_until='domcontentloaded', timeout=30000)

                print("Waiting for page to load...")
                time.sleep(3)

                if not captured_headers:
                    print("\nAttempting to trigger API calls by navigating to Library...")
                    try:
                        # Try to navigate to Library to trigger API calls
                        page.goto('https://music.youtube.com/library', wait_until='domcontentloaded', timeout=15000)
                        time.sleep(3)
                    except Exception as e:
                        print(f"Note: Could not navigate to Library automatically: {e}")

                if not captured_headers:
                    print("\n" + "="*60)
                    print("Manual steps needed:")
                    print("="*60)
                    print("In the browser window:")
                    print("1. Make sure you're logged in to your Google/YouTube account")
                    print("2. Click on 'Library' in the left sidebar")
                    print("3. Or click on any playlist")
                    print("4. Or search for a song")
                    print("\nWaiting for authentication headers to be captured...")
                    print("(Window will close automatically once detected)\n")

                    # Wait for headers to be captured
                    max_wait = 90  # 1.5 minutes
                    waited = 0
                    while not captured_headers and waited < max_wait:
                        time.sleep(1)
                        waited += 1

                        if waited % 15 == 0:
                            print(f"  Still waiting... ({max_wait - waited}s remaining)")
                            if request_count > 0:
                                print(f"  Detected {request_count} total requests ({post_count} POST)")
                            else:
                                print(f"  No API requests detected yet - try interacting with the page")

                if not captured_headers:
                    # Save browser state for future use
                    if not os.path.exists(user_data_dir):
                        os.makedirs(user_data_dir)
                    context.storage_state(path=os.path.join(user_data_dir, 'state.json'))

                    browser.close()

                    print("\n✗ Timeout: Could not capture authentication headers")
                    print("Please try again and make sure to:")
                    print("  - Log in to YouTube Music")
                    print("  - Navigate around the site (Library, playlists, etc.)")
                    print("\nNote: Your login session has been saved for next time.")
                    return False

                # Format headers for ytmusicapi (BEFORE closing browser!)
                print("\nFormatting headers for ytmusicapi...")

                # Get cookies from browser context (ytmusicapi needs these!)
                print("Extracting cookies from browser context...")
                cookies = context.cookies('https://music.youtube.com')

                # Format cookies as a Cookie header string
                cookie_string = '; '.join([f"{c['name']}={c['value']}" for c in cookies])
                print(f"Found {len(cookies)} cookies")

                # Save browser state for future use
                if not os.path.exists(user_data_dir):
                    os.makedirs(user_data_dir)
                context.storage_state(path=os.path.join(user_data_dir, 'state.json'))

                # NOW close the browser
                browser.close()

                # ytmusicapi expects specific headers
                required_headers = {}
                header_mapping = {
                    'cookie': 'Cookie',
                    'authorization': 'Authorization',
                    'user-agent': 'User-Agent',
                    'x-goog-authuser': 'X-Goog-AuthUser',
                    'x-origin': 'X-Origin',
                    'x-goog-visitor-id': 'X-Goog-Visitor-Id',
                    'accept': 'Accept',
                    'accept-language': 'Accept-Language',
                    'content-type': 'Content-Type',
                    'origin': 'Origin',
                    'referer': 'Referer',
                }

                for key, value in captured_headers.items():
                    lower_key = key.lower()
                    if lower_key in header_mapping:
                        required_headers[header_mapping[lower_key]] = value

                # Add cookies from browser context (critical for ytmusicapi)
                if cookie_string:
                    required_headers['Cookie'] = cookie_string
                    print("✓ Cookies added to headers")

                # Add default headers if missing
                if 'Accept' not in required_headers:
                    required_headers['Accept'] = '*/*'
                if 'Content-Type' not in required_headers:
                    required_headers['Content-Type'] = 'application/json'
                if 'User-Agent' not in required_headers:
                    required_headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                if 'Origin' not in required_headers:
                    required_headers['Origin'] = 'https://music.youtube.com'
                if 'Referer' not in required_headers:
                    required_headers['Referer'] = 'https://music.youtube.com/'

                # Save to file
                print(f"Saving headers to {output_file}...")
                with open(output_file, 'w') as f:
                    json.dump(required_headers, f, indent=2)

                print(f"\n✓ Authentication headers saved to {output_file}")

                # Verify authentication works
                print("\nVerifying authentication...")
                try:
                    test_ytmusic = YTMusic(output_file)
                    # Try a simple API call
                    test_ytmusic.get_library_playlists(limit=1)
                    print("✓ Authentication verified successfully!")

                    print(f"\n{'='*60}")
                    print("Setup Complete!")
                    print(f"{'='*60}")
                    print(f"You can now use the script to export playlists.")
                    print(f"Your authentication is saved in: {output_file}\n")

                    return True

                except Exception as e:
                    print(f"\n✗ Authentication verification failed: {e}")
                    print("The headers were captured but may not be valid.")
                    print("Please try running the setup again.")
                    return False

        except Exception as e:
            print(f"\n✗ ERROR: {e}")
            print("\nSetup failed. Please try again or use manual setup:")
            print("  Run: ytmusicapi browser")
            return False

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

    def list_youtube_playlists(self):
        """
        List all YouTube Music playlists for the authenticated user.
        """
        print(f"\n{'='*60}")
        print("Your YouTube Music Playlists")
        print(f"{'='*60}\n")

        try:
            # Fetch all playlists from YouTube Music
            playlists = self.ytmusic.get_library_playlists(limit=None)

            if not playlists:
                print("No playlists found.")
                return

            print(f"Found {len(playlists)} playlist(s):\n")

            for idx, playlist in enumerate(playlists, 1):
                name = playlist.get('title', 'Unknown')
                playlist_id = playlist.get('playlistId', 'Unknown')
                track_count = playlist.get('count', 0)

                # Handle count being returned as string or int
                if isinstance(track_count, str):
                    try:
                        track_count = int(track_count.replace(',', ''))
                    except:
                        track_count = '?'

                print(f"{idx}. {name}")
                print(f"   ID: {playlist_id}")
                print(f"   Tracks: {track_count}")
                print(f"   URL: https://music.youtube.com/playlist?list={playlist_id}")
                print()

        except Exception as e:
            print(f"ERROR: Failed to fetch YouTube Music playlists: {e}")
            print("\nMake sure you're authenticated with YouTube Music.")
            print("Run 'ytmusicapi oauth' or 'ytmusicapi browser' to set up authentication.")
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

        Skips results where the user has previously disliked (downvoted) the song.

        Args:
            track: Dictionary containing track info (name, artists, etc.)

        Returns:
            YouTube Music video ID if found and not disliked, None otherwise
        """
        try:
            # Create search query
            artist_names = ', '.join(track['artists'])
            query = f"{track['name']} {artist_names}"

            # Search on YouTube Music
            search_results = self.ytmusic.search(query, filter='songs', limit=5)

            if not search_results:
                return None

            # Return the first result that hasn't been downvoted
            for result in search_results:
                if result.get('likeStatus') == 'DISLIKE':
                    print(f"  (skipping disliked result: {result.get('title', 'unknown')})", end=' ')
                    continue
                return result['videoId']

            # All results were disliked
            return None

        except Exception as e:
            print(f"  Warning: Failed to search for track '{track['name']}': {e}")
            return None

    def get_youtube_playlist(self, playlist_id: str) -> Dict:
        """
        Fetch an existing YouTube Music playlist and its tracks.

        Args:
            playlist_id: YouTube Music playlist ID

        Returns:
            Dictionary containing playlist info and tracks
        """
        try:
            playlist = self.ytmusic.get_playlist(playlist_id, limit=None)
            return playlist
        except Exception as e:
            print(f"ERROR: Failed to fetch YouTube Music playlist: {e}")
            raise

    def backup_playlist(self, playlist_data: Dict, backup_dir: str = 'backups') -> str:
        """
        Backup a YouTube Music playlist to a JSON file.

        Args:
            playlist_data: Playlist data from get_youtube_playlist
            backup_dir: Directory to store backups

        Returns:
            Path to the backup file
        """
        try:
            # Resolve backup directory relative to script directory
            if not os.path.isabs(backup_dir):
                backup_dir = os.path.join(SCRIPT_DIR, backup_dir)
            # Create backup directory if it doesn't exist
            os.makedirs(backup_dir, exist_ok=True)

            # Generate backup filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            playlist_id = playlist_data.get('id', 'unknown')
            playlist_name = playlist_data.get('title', 'unknown').replace('/', '_')
            backup_filename = f"playlist_backup_{playlist_name}_{playlist_id}_{timestamp}.json"
            backup_path = os.path.join(backup_dir, backup_filename)

            # Save playlist data to file
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(playlist_data, f, indent=2, ensure_ascii=False)

            return backup_path

        except Exception as e:
            print(f"Warning: Failed to create backup: {e}")
            return None

    def _extract_base_song_name(self, text: str) -> str:
        """
        Extract the base song name by taking text up to the first separator.

        This handles the common pattern where Spotify and YouTube Music format
        remixes/versions differently:
        - Spotify: "Song Name - Remix Info" or "Song Name (Remix Info)"
        - YouTube: "Song Name (Remix Info)" or "Song Name - Remix Info"

        By extracting just the base name, we can match tracks regardless of
        how the remix/version info is formatted.

        Args:
            text: Full track name

        Returns:
            Base song name (lowercase, trimmed)
        """
        if not text:
            return ''

        # Find the first occurrence of ' - ' or '('
        # We look for ' - ' (with spaces) to avoid splitting on hyphenated words
        dash_pos = text.find(' - ')
        paren_pos = text.find('(')

        # Find the earliest separator
        positions = []
        if dash_pos != -1:
            positions.append(dash_pos)
        if paren_pos != -1:
            positions.append(paren_pos)

        if positions:
            split_pos = min(positions)
            text = text[:split_pos]

        # Normalize: lowercase, strip whitespace
        return text.lower().strip()

    def compare_playlists(self, spotify_tracks: List[Dict], youtube_tracks: List[Dict]) -> Tuple[List[Dict], List[str]]:
        """
        Compare Spotify and YouTube Music playlists to find differences.

        Comparison is done using only the base song name (up to the first
        separator like '-' or '('), ignoring artist names. This handles
        the common case where Spotify and YouTube Music format track names
        differently (e.g., "Song - Remix" vs "Song (Remix)").

        Args:
            spotify_tracks: List of tracks from Spotify playlist
            youtube_tracks: List of tracks from YouTube Music playlist

        Returns:
            Tuple of (tracks_to_add, items_to_remove)
            - tracks_to_add: Spotify tracks not in YouTube Music
            - items_to_remove: YouTube Music setVideoIds to remove
        """
        # Create a set of base song names from YouTube Music
        # Using only the base song name (before first separator) as the signature
        youtube_signatures = set()
        youtube_items_map = {}  # Map signature to setVideoId for removal

        for yt_track in youtube_tracks:
            if not yt_track:
                continue

            # Extract base song name (up to first '-' or '(')
            base_name = self._extract_base_song_name(yt_track.get('title', ''))

            if base_name:
                youtube_signatures.add(base_name)
                # Store setVideoId for potential removal
                if 'setVideoId' in yt_track:
                    youtube_items_map[base_name] = yt_track['setVideoId']

        # Find Spotify tracks not in YouTube Music
        tracks_to_add = []
        spotify_signatures = set()

        for sp_track in spotify_tracks:
            # Extract base song name (up to first '-' or '(')
            base_name = self._extract_base_song_name(sp_track['name'])

            if base_name:
                spotify_signatures.add(base_name)

                if base_name not in youtube_signatures:
                    tracks_to_add.append(sp_track)

        # Find YouTube Music tracks not in Spotify (to remove)
        items_to_remove = []
        for yt_base_name, set_video_id in youtube_items_map.items():
            if yt_base_name not in spotify_signatures:
                items_to_remove.append({
                    'videoId': None,  # Not needed for removal
                    'setVideoId': set_video_id
                })

        return tracks_to_add, items_to_remove

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

    def update_playlist(self, spotify_playlist_id: str, youtube_playlist_id: str,
                       create_backup: bool = True):
        """
        Update an existing YouTube Music playlist to match a Spotify playlist.

        Args:
            spotify_playlist_id: Spotify playlist ID or URL
            youtube_playlist_id: YouTube Music playlist ID to update
            create_backup: Whether to backup the playlist before updating
        """
        print(f"\n{'='*60}")
        print("Spotify to YouTube Music Playlist Update")
        print(f"{'='*60}\n")

        backup_path = None

        try:
            # Fetch current YouTube Music playlist
            print("Fetching current YouTube Music playlist...")
            try:
                youtube_playlist = self.get_youtube_playlist(youtube_playlist_id)
                yt_track_count = len(youtube_playlist.get('tracks', []))
                print(f"✓ Found playlist: '{youtube_playlist['title']}' ({yt_track_count} tracks)")
            except Exception as e:
                print(f"ERROR: Failed to fetch YouTube Music playlist.")
                print(f"Make sure the playlist ID is correct and you have access to it.")
                self.email_notifier.send_error("Playlist Update", f"Failed to fetch YouTube Music playlist: {e}")
                sys.exit(1)

            # Backup the playlist if requested
            if create_backup:
                print("\nBacking up current playlist...")
                backup_path = self.backup_playlist(youtube_playlist)
                if backup_path:
                    print(f"✓ Backup saved to: {backup_path}")
                else:
                    print("Warning: Backup failed, but continuing with update...")

            # Fetch Spotify playlist
            print("\nFetching Spotify playlist...")
            try:
                spotify_playlist = self.get_spotify_playlist(spotify_playlist_id)
                print(f"✓ Found playlist: '{spotify_playlist['name']}' ({spotify_playlist['total_tracks']} tracks)")
            except Exception as e:
                print(f"ERROR: Failed to fetch Spotify playlist: {e}")
                if create_backup and backup_path:
                    print(f"Your YouTube Music playlist was backed up to: {backup_path}")
                self.email_notifier.send_error("Playlist Update", f"Failed to fetch Spotify playlist: {e}")
                sys.exit(1)

            # Compare playlists to find differences
            print("\nComparing playlists...")
            tracks_to_add, items_to_remove = self.compare_playlists(
                spotify_playlist['tracks'],
                youtube_playlist.get('tracks', [])
            )

            print(f"  Tracks to add: {len(tracks_to_add)}")
            print(f"  Tracks to remove: {len(items_to_remove)}")

            if not tracks_to_add and not items_to_remove:
                print("\n✓ Playlists are already in sync! No changes needed.")
                return

            # Collect removed track names before removing them
            removed_track_names = []
            if items_to_remove:
                # Map items_to_remove back to track names from YouTube playlist
                youtube_tracks_dict = {}
                for yt_track in youtube_playlist.get('tracks', []):
                    if yt_track and 'setVideoId' in yt_track:
                        track_name = yt_track.get('title', '')
                        artists = yt_track.get('artists', [])
                        # Join all artist names (same as we do for added tracks)
                        if artists:
                            artist_names = [a.get('name', '') for a in artists if a.get('name')]
                            artist_string = ', '.join(artist_names)
                        else:
                            artist_string = ''
                        display_name = f"{track_name} - {artist_string}" if artist_string else track_name
                        youtube_tracks_dict[yt_track['setVideoId']] = display_name

                for item in items_to_remove:
                    set_video_id = item.get('setVideoId')
                    if set_video_id and set_video_id in youtube_tracks_dict:
                        removed_track_names.append(youtube_tracks_dict[set_video_id])

            # Remove tracks that are no longer in Spotify
            if items_to_remove:
                print(f"\nRemoving {len(items_to_remove)} tracks from YouTube Music...")
                try:
                    self.ytmusic.remove_playlist_items(youtube_playlist_id, items_to_remove)
                    print(f"✓ Removed {len(items_to_remove)} tracks")
                except Exception as e:
                    error_msg = f"Failed to remove tracks: {e}"
                    print(f"ERROR: {error_msg}")
                    print("Update aborted. Check your backup if needed.")
                    self.email_notifier.send_error("Playlist Update", error_msg)
                    sys.exit(1)

            # Search for and add new tracks
            video_ids = []
            added_track_names = []
            not_found = []
            if tracks_to_add:
                print(f"\nSearching for {len(tracks_to_add)} new tracks on YouTube Music...")

                for idx, track in enumerate(tracks_to_add, 1):
                    artist_names = ', '.join(track['artists'])
                    track_display = f"{track['name']} - {artist_names}"
                    print(f"  [{idx}/{len(tracks_to_add)}] {track_display}...", end=' ')

                    video_id = self.search_youtube_music_track(track)

                    if video_id:
                        video_ids.append(video_id)
                        added_track_names.append(track_display)
                        print("✓")
                    else:
                        not_found.append(track_display)
                        print("✗ Not found")

                # Add the new tracks
                if video_ids:
                    print(f"\nAdding {len(video_ids)} new tracks to YouTube Music...")
                    try:
                        batch_size = 50
                        for i in range(0, len(video_ids), batch_size):
                            batch = video_ids[i:i + batch_size]
                            self.ytmusic.add_playlist_items(youtube_playlist_id, batch)
                            print(f"  Added batch {i//batch_size + 1} ({len(batch)} tracks)")
                        print(f"✓ Added {len(video_ids)} new tracks")
                    except Exception as e:
                        error_msg = f"Failed to add tracks: {e}"
                        print(f"ERROR: {error_msg}")
                        print("Some tracks may have been removed but not all new tracks were added.")
                        print(f"Check your backup if needed: {backup_path if create_backup else 'No backup'}")
                        self.email_notifier.send_error("Playlist Update", error_msg)
                        sys.exit(1)

                if not_found:
                    print(f"\nTracks not found on YouTube Music ({len(not_found)}):")
                    for track in not_found[:10]:
                        print(f"  - {track}")
                    if len(not_found) > 10:
                        print(f"  ... and {len(not_found) - 10} more")

            # Summary
            final_count = yt_track_count - len(items_to_remove) + len(video_ids)
            print(f"\n{'='*60}")
            print("✓ Update complete!")
            print(f"{'='*60}")
            print(f"Playlist: {youtube_playlist['title']}")
            print(f"Tracks removed: {len(items_to_remove)}")
            print(f"Tracks added: {len(video_ids)}")
            print(f"Final track count: {final_count}")
            if create_backup and backup_path:
                print(f"Backup: {backup_path}")

            # Send update completion notification
            self.email_notifier.send_update_complete(
                youtube_playlist['title'],
                added_track_names,
                removed_track_names,
                not_found,
                final_count,
                backup_path
            )

        except Exception as e:
            # Send error notification for unexpected errors
            self.email_notifier.send_error("Playlist Update", str(e))
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

        try:
            # Fetch Spotify playlist
            print("Fetching Spotify playlist...")
            playlist = self.get_spotify_playlist(spotify_playlist_id)
            print(f"✓ Found playlist: '{playlist['name']}' ({playlist['total_tracks']} tracks)")

            # Search for tracks on YouTube Music
            print(f"\nSearching for tracks on YouTube Music...")
            video_ids = []
            added_tracks = []
            not_found = []

            for idx, track in enumerate(playlist['tracks'], 1):
                artist_names = ', '.join(track['artists'])
                track_display = f"{track['name']} - {artist_names}"
                print(f"  [{idx}/{playlist['total_tracks']}] {track_display}...", end=' ')

                video_id = self.search_youtube_music_track(track)

                if video_id:
                    video_ids.append(video_id)
                    added_tracks.append(track_display)
                    print("✓")
                else:
                    not_found.append(track_display)
                    print("✗ Not found")

            print(f"\n✓ Found {len(video_ids)}/{playlist['total_tracks']} tracks on YouTube Music")

            if not_found:
                print(f"\nTracks not found ({len(not_found)}):")
                for track in not_found[:10]:  # Show first 10
                    print(f"  - {track}")
                if len(not_found) > 10:
                    print(f"  ... and {len(not_found) - 10} more")

            # Create YouTube Music playlist
            playlist_url = None
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

                playlist_url = f"https://music.youtube.com/playlist?list={playlist_id}"

                print(f"\n{'='*60}")
                print("✓ Export complete!")
                print(f"{'='*60}")
                print(f"Playlist URL: {playlist_url}")
                print(f"Tracks added: {len(video_ids)}/{playlist['total_tracks']}")

                # Send completion notification
                self.email_notifier.send_export_complete(
                    playlist['name'],
                    playlist['total_tracks'],
                    len(video_ids),
                    added_tracks,
                    not_found,
                    playlist_url
                )
            else:
                print("\n✗ No tracks were found on YouTube Music. Playlist not created.")
                # Send completion notification with zero tracks found
                self.email_notifier.send_export_complete(
                    playlist['name'],
                    playlist['total_tracks'],
                    0,
                    [],
                    not_found,
                    None
                )

        except Exception as e:
            # Send error notification
            self.email_notifier.send_error("Playlist Export", str(e))
            raise


def main():
    parser = argparse.ArgumentParser(
        description='Export or update a Spotify playlist to YouTube Music',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Set up YouTube Music authentication (first time)
  %(prog)s --setup-youtube

  # List your Spotify playlists
  %(prog)s --list-spotify

  # List your YouTube Music playlists
  %(prog)s --list-youtube

  # Export a new playlist
  %(prog)s https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
  %(prog)s 37i9dQZF1DXcBWIGoYBM5M --privacy PUBLIC

  # Update an existing YouTube Music playlist
  %(prog)s SPOTIFY_ID --update YOUTUBE_MUSIC_PLAYLIST_ID
  %(prog)s SPOTIFY_ID --update YT_PLAYLIST_ID --no-backup

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
        '--list-spotify',
        action='store_true',
        help='List all your Spotify playlists and their IDs'
    )

    parser.add_argument(
        '--list-youtube',
        action='store_true',
        help='List all your YouTube Music playlists and their IDs'
    )

    parser.add_argument(
        '--setup-youtube',
        action='store_true',
        help='Automatically set up YouTube Music authentication using browser'
    )

    parser.add_argument(
        '--update',
        metavar='YT_PLAYLIST_ID',
        help='Update an existing YouTube Music playlist instead of creating a new one'
    )

    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Skip backup when updating a playlist (not recommended)'
    )

    parser.add_argument(
        '--privacy',
        choices=['PRIVATE', 'PUBLIC', 'UNLISTED'],
        default='PRIVATE',
        help='YouTube Music playlist privacy setting for new playlists (default: PRIVATE)'
    )

    parser.add_argument(
        '--no-email',
        action='store_true',
        help='Disable email notifications for this run (even if enabled in config)'
    )

    args = parser.parse_args()

    try:
        # Handle setup command separately (doesn't need full initialization)
        if args.setup_youtube:
            exporter = SpotifyToYouTubeMusic(skip_youtube_auth=True, disable_email=args.no_email)
            exporter.setup_youtube_auth_interactive()
            sys.exit(0)

        exporter = SpotifyToYouTubeMusic(disable_email=args.no_email)

        if args.list_spotify:
            exporter.list_user_playlists()
        elif args.list_youtube:
            exporter.list_youtube_playlists()
        elif args.playlist_id:
            if args.update:
                # Update existing playlist
                create_backup = not args.no_backup
                exporter.update_playlist(args.playlist_id, args.update, create_backup)
            else:
                # Export as new playlist
                exporter.export_playlist(args.playlist_id, args.privacy)
        else:
            parser.print_help()
            print("\nERROR: Please provide a playlist ID or use --list to see your playlists")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
