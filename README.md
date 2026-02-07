# Plex Telegram Bot

A comprehensive Telegram bot for managing and monitoring a Plex media server with integrated request system.

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-donate-yellow?style=flat-square&logo=buy-me-a-coffee)](https://buymeacoffee.com/Stovenovens)

## Features

- 🎥 **Now Playing** - View current streams on Plex
- 📊 **Statistics** - Weekly viewing stats and leaderboards  
- 📅 **Upcoming Releases** - TV episodes and movies from Sonarr/Radarr
- 🔥 **Trending Content** - Hot movies and shows from TMDB
- 🔌 **Server Control** - Wake-on-LAN and remote shutdown
- ⏰ **Scheduled Wake** - Automatic server wake at configured times
- 🎬 **Request System** - Search and request movies/TV shows directly to Radarr/Sonarr

## Commands

**Note:** If `BOT_TOPIC_ID` is configured, all commands must be sent in that topic. Commands sent in other topics will be silently ignored. If not configured, the bot responds in any chat/topic.

### Request Commands
- `/movie <title>` - Search for movies to request
- `/series <title>` or `/tv <title>` - Search for TV series to request
- `/myrequests` or `/requests` - View your request history and status

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
- **Request Tracking** - Automatic notifications when your requested content is available
- **Status Monitoring** - Check status of all your requests with `/myrequests`

### Request Workflow

1. User searches: `/movie Inception` or `/series Breaking Bad`
2. Bot displays TMDB results with interactive buttons
3. User can browse results using Previous/Next buttons
4. Click "Add Movie/Series" to add to Radarr/Sonarr
5. Select root folder and quality profile (if multiple configured)
6. Content is automatically added and searched for
7. Bot tracks download progress and notifies you when available (every 15 minutes)
8. View all your requests with `/myrequests`

## Setup

1. Clone this repository
2. Create virtual environment: `python3 -m venv venv`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and configure your settings
5. Run the bot: `python main.py`

## Docker Deployment

### Quick Start

```bash
git clone https://github.com/stovenovens/Plexbot.git
cd Plexbot
cp .env.example .env
# Edit .env with your settings
docker compose up -d
```

### Managing the Bot

```bash
# View logs
docker compose logs -f

# Stop the bot
docker compose down

# Restart after config changes
docker compose restart

# Rebuild after code updates
docker compose up -d --build
```

### Data Persistence

Request tracking data is stored in the `data/` directory, which is mounted as a volume. Your data persists across container restarts and rebuilds.

### Wake-on-LAN Note

The Docker setup uses `network_mode: host` so that Wake-on-LAN broadcast packets can reach your local network. This means the container shares your host's network stack. If you run the bot on a machine that is not on the same LAN as your Plex server, WOL will not work regardless of Docker configuration.

## Configuration

### Required
- `BOT_TOKEN` - Your Telegram bot token
- `GROUP_CHAT_ID` - Your Telegram group chat ID
- `TAUTILLI_URL` and `TAUTILLI_API_KEY` - For Plex monitoring
- `TMDB_API_READ_TOKEN` - For movie/TV search and trending content

### Bot Topic (Optional)
- `BOT_TOPIC_ID` - Restrict the bot to a specific Telegram topic. If not set, the bot responds in any chat/topic

### Request System
- `RADARR_URL` and `RADARR_API_KEY` - For movie requests
- `SONARR_URL` and `SONARR_API_KEY` - For TV series requests

### Wake-on-LAN & Server Control
- `PLEX_SERVER_MAC` and `PLEX_BROADCAST_IP` - For Wake-on-LAN
- `PLEX_SERVER_IP`, `PLEX_SSH_USER`, `PLEX_SSH_PASSWORD` - For remote shutdown
- `OFF_USER_IDS` - Comma-separated Telegram user IDs allowed to run `/off` and admin commands

### Schedule Settings
- `WEEKDAY_WAKE_HOUR`, `WEEKDAY_WAKE_MINUTE` - Auto-wake time on weekdays (default: 17:30)
- `WEEKEND_WAKE_HOUR`, `WEEKEND_WAKE_MINUTE` - Auto-wake time on weekends (default: 18:00)
- `AUTO_SHUTDOWN_ENABLED` - Enable automatic shutdown (default: false)
- `AUTO_SHUTDOWN_HOUR`, `AUTO_SHUTDOWN_MINUTE` - Shutdown time (default: 1:00 AM)
- `AUTO_SHUTDOWN_RECHECK_MINUTES` - Minutes to wait before rechecking for active streams (default: 30)

### Notifications
- `SILENT_NOTIFICATIONS` - Disable notification sounds (default: true)

See `.env.example` for all available configuration options.

## Automated Features

### Auto-Wake
- **Auto-wake weekdays:** 5:30 PM (configurable)
- **Auto-wake weekends:** 6:00 PM (configurable)
- **Smart server detection** - Skips wake if already online
- **30-minute grace period** - For missed schedules

### Auto-Shutdown (Optional)
- **Smart shutdown at 1:00 AM** (configurable, disabled by default)
- **Active stream detection** - Checks Tautulli for active viewers
- **Delayed shutdown** - If streams are active, rechecks every 30 minutes
- **Automatic retry** - Continues checking until no active streams
- **Notifications** - Telegram alerts for all shutdown events

### Other
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

## File Structure

```
Plexbot/
├── main.py                          # Main bot entry point
├── config.py                        # Configuration and environment variables
├── requirements.txt                 # Python dependencies
├── .env                             # Your configuration (create from .env.example)
├── .env.example                     # Configuration template
├── commands/
│   ├── __init__.py
│   ├── admin_commands.py            # Debug, logs, info, welcome commands
│   ├── media_commands.py            # Now playing, stats, trending, upcoming, search
│   ├── server_commands.py           # Wake, shutdown, status commands
│   ├── request_commands.py          # Movie/TV search and request system
│   ├── request_callbacks.py         # Interactive button handlers
│   └── request_status_commands.py   # /myrequests command
├── utils/
│   ├── __init__.py
│   ├── helpers.py                   # Shared utility functions
│   ├── logging_setup.py             # Session-based logging
│   ├── server_status.py             # Server monitoring and wake functions
│   ├── request_tracker.py           # Request persistence and status tracking
│   └── recently_added.py            # Plex content notification system
└── data/
    └── requests.json                # Request tracking database
```

## Contributing

Contributions are welcome! Feel free to:

1. Fork the repository
2. Create a feature branch
3. Submit a pull request

Bug reports and feature requests are also appreciated via [Issues](https://github.com/stovenovens/Plexbot/issues).

## Support

If you find this bot useful, consider supporting development:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-donate-yellow?style=flat-square&logo=buy-me-a-coffee)](https://buymeacoffee.com/Stovenovens)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Changelog

### v2.0 - Request System Integration
- Added movie and TV series request functionality
- TMDB search integration with interactive navigation
- Automatic Radarr/Sonarr integration
- Support for multiple root folders and quality profiles
- Smart detection of existing content
- Group chat optimized workflow

### v1.0 - Initial Release
- Plex monitoring via Tautulli
- Automated wake-on-LAN scheduling
- Statistics and trending content
- Server control and admin functions