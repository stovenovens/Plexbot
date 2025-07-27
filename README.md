# Plex Telegram Bot

A comprehensive Telegram bot for managing and monitoring a Plex media server.

## Features

- 🎥 **Now Playing** - View current streams across Plex and Jellyfin
- 📊 **Statistics** - Weekly viewing stats and leaderboards  
- 📅 **Upcoming Releases** - TV episodes and movies from Sonarr/Radarr
- 🔥 **Trending Content** - Hot movies and shows from TMDB
- 🔌 **Server Control** - Wake-on-LAN and remote shutdown
- ⏰ **Scheduled Wake** - Automatic server wake at configured times

## Commands

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
- `/info` - Show help and available commands

## Setup

1. Clone this repository
2. Create virtual environment: `python3 -m venv venv`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and configure your settings
5. Run the bot: `python main.py`

## License

Private project - not for redistribution.
