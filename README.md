# Plex Telegram Bot

A comprehensive Telegram bot for managing and monitoring a Plex media server with integrated request system.

## Features

- 🎥 **Now Playing** - View current streams across Plex and Jellyfin
- 📊 **Statistics** - Weekly viewing stats and leaderboards  
- 📅 **Upcoming Releases** - TV episodes and movies from Sonarr/Radarr
- 🔥 **Trending Content** - Hot movies and shows from TMDB
- 🔌 **Server Control** - Wake-on-LAN and remote shutdown
- ⏰ **Scheduled Wake** - Automatic server wake at configured times
- 🎬 **Request System** - Search and request movies/TV shows directly to Radarr/Sonarr

## Commands

### Request Commands
- `/movie <title>` - Search for movies to request
- `/series <title>` or `/tv <title>` - Search for TV series to request

### Media Commands
- `/nowplaying` or `/np` - Show current streams
- `/stats` - Weekly viewing statistics
- `/upcoming` or `/up` - Show upcoming releases
- `/hot` - Show trending content

### Server Commands  
- `/on` - Wake server with Wake-on-LAN
- `/off` - Shutdown server (authorized users)
- `/status` - Check server status

### Admin Commands
- `/debug` - Show bot configuration
- `/logs` - View recent logs (authorized users) 
- `/testjellyfin` - Test Jellyfin API
- `/testwake` - Test Wake-on-LAN
- `/info` - Show help and available commands

## Request System

The bot includes a Searcharr-like request system that allows anyone in the group chat to search for and request movies/TV shows without authentication. Features include:

- **TMDB Integration** - High-quality search results with posters, ratings, and descriptions
- **Interactive Navigation** - Browse through search results with Previous/Next buttons
- **Smart Detection** - Automatically detects if content is already in your library
- **Flexible Configuration** - Supports multiple root folders and quality profiles
- **One-Click Adding** - Add content directly to Radarr/Sonarr with minimal clicks
- **External Links** - Quick access to TMDB and IMDb pages

### Request Workflow

1. User searches: `/movie Inception` or `/series Breaking Bad`
2. Bot displays TMDB results with interactive buttons
3. User can browse results using Previous/Next buttons
4. Click "Add Movie/Series" to add to Radarr/Sonarr
5. Select root folder and quality profile (if multiple configured)
6. Content is automatically added and searched for

## Setup

1. Clone this repository
2. Create virtual environment: `python3 -m venv venv`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and configure your settings
5. Run the bot: `python main.py`

## Configuration

### Required for Basic Functionality
- `BOT_TOKEN` - Your Telegram bot token
- `GROUP_CHAT_ID` - Your Telegram group chat ID
- `TAUTILLI_URL` and `TAUTILLI_API_KEY` - For Plex monitoring
- `TMDB_API_READ_TOKEN` - For movie/TV search and trending content

### Required for Request System
- `RADARR_URL` and `RADARR_API_KEY` - For movie requests
- `SONARR_URL` and `SONARR_API_KEY` - For TV series requests

### Optional Features
- `JELLYFIN_URL` and `JELLYFIN_API_KEY` - For Jellyfin monitoring
- `PLEX_SERVER_MAC` and `PLEX_BROADCAST_IP` - For Wake-on-LAN
- `PLEX_SERVER_IP`, `PLEX_SSH_USER`, `PLEX_SSH_PASSWORD` - For remote shutdown

See `.env.example` for all available configuration options.

## Automated Features

- **Auto-wake weekdays:** 4:30 PM (configurable)
- **Auto-wake weekends:** 10:00 AM (configurable)
- **Smart server detection** - Skips wake if already online
- **30-minute grace period** - For missed schedules
- **Silent notifications** - Configurable notification sounds

## Request System vs Searcharr

This integrated request system provides several advantages over running a separate Searcharr instance:

- **No Authentication Required** - Works for all group members immediately
- **Unified Interface** - All bot functions in one place
- **Group Chat Friendly** - Responses go to dedicated bot topic
- **Simplified Setup** - No separate bot or database required
- **Smart Responses** - Redirects responses to keep main chat clean
- **Same API Integration** - Uses your existing Sonarr/Radarr setup

## Security & Permissions

The request system is designed for trusted group environments:

- **Open Access** - Any group member can request content
- **Admin Controls** - Server shutdown and logs require authorization
- **Safe Defaults** - Requests use configured quality profiles and root folders
- **Clean Separation** - All responses go to the bot topic thread

## Troubleshooting

### Request System Issues

1. **"TMDB API not configured"** - Add your TMDB API key to `.env`
2. **"Radarr/Sonarr not configured"** - Check URL and API key settings
3. **"All API versions failed"** - Verify Radarr/Sonarr are accessible and running
4. **"Could not find TVDB ID"** - Some TV shows may not have TVDB mappings

### General Issues

1. **Bot not responding** - Check bot token and group chat ID
2. **Commands not working** - Ensure bot has necessary permissions in group
3. **Wake-on-LAN not working** - Verify MAC address and broadcast IP
4. **Stats not showing** - Check Tautulli URL and API key

## API Requirements

- **Telegram Bot API** - For bot functionality
- **TMDB API** - For search results and trending content (free)
- **Tautulli API** - For Plex monitoring and statistics
- **Radarr API v1/v2/v3** - For movie management (auto-detected)
- **Sonarr API v1/v2/v3** - For TV series management (auto-detected)
- **Jellyfin API** - Optional, for additional monitoring

## File Structure

```
plex_bot/
├── main.py                    # Main bot entry point
├── config.py                  # Configuration and environment variables
├── requirements.txt           # Python dependencies
├── .env                      # Your configuration (create from .env.example)
├── .env.example              # Configuration template
├── commands/
│   ├── __init__.py
│   ├── admin_commands.py     # Debug, logs, info commands
│   ├── media_commands.py     # Now playing, stats, trending, upcoming
│   ├── server_commands.py    # Wake, shutdown, status commands
│   ├── request_commands.py   # Movie/TV search and request system
│   └── request_callbacks.py  # Interactive button handlers
└── utils/
    ├── __init__.py
    ├── helpers.py            # Shared utility functions
    ├── logging_setup.py      # Session-based logging
    └── server_status.py      # Server monitoring and wake functions
```

## Contributing

This is a private project, but you can:

1. Fork the repository for your own modifications
2. Submit issues for bugs or feature requests
3. Adapt the request system for your own bots

## License

Private project - not for redistribution.

## Changelog

### v2.0 - Request System Integration
- Added movie and TV series request functionality
- TMDB search integration with interactive navigation
- Automatic Radarr/Sonarr integration
- Support for multiple root folders and quality profiles
- Smart detection of existing content
- Group chat optimized workflow

### v1.0 - Initial Release
- Plex and Jellyfin monitoring
- Automated wake-on-LAN scheduling
- Statistics and trending content
- Server control and admin functions