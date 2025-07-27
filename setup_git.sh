#!/bin/bash
# Git setup script for Plex Bot

echo "🚀 Setting up Git repository for Plex Bot..."

# Navigate to bot directory
cd ~/plex_bot

# Initialize git repository
git init

# Create .gitignore file to exclude sensitive files
cat > .gitignore << 'EOF'
# Environment variables (NEVER commit these!)
.env
*.env

# Log files
*.log
bot.log

# Python cache
__pycache__/
*.pyc
*.pyo
*.pyd
.Python

# Virtual environment
venv/
env/
ENV/

# IDE files
.vscode/
.idea/
*.swp
*.swo

# OS files
.DS_Store
Thumbs.db

# Backup files
*.backup
*.bak
*.old

# Service files (contain paths specific to your system)
*.service
EOF

# Create README.md
cat > README.md << 'EOF'
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

## Configuration

See `.env.example` for all available configuration options.

## License

Private project - not for redistribution.
EOF

# Create .env.example (template without real values)
cat > .env.example << 'EOF'
# === REQUIRED SETTINGS ===
BOT_TOKEN=your_bot_token_here
GROUP_CHAT_ID=-1001234567890
BOT_TOPIC_ID=15980

# === PLEX/TAUTULLI SETTINGS ===
TAUTILLI_URL=http://192.168.1.30:8181
TAUTILLI_API_KEY=your_tautulli_api_key

# === JELLYFIN SETTINGS (Optional) ===
JELLYFIN_URL=http://192.168.1.30:8096
JELLYFIN_API_KEY=your_jellyfin_api_key

# === WAKE-ON-LAN SETTINGS ===
PLEX_SERVER_MAC=your:mac:address:here
PLEX_BROADCAST_IP=192.168.1.255

# === SSH SHUTDOWN SETTINGS ===
PLEX_SERVER_IP=192.168.1.30
PLEX_SSH_USER=your_username
PLEX_SSH_PASSWORD=your_password

# === AUTHORIZATION ===
OFF_USER_IDS=123456789,987654321

# === SCHEDULE SETTINGS ===
WEEKDAY_WAKE_HOUR=16
WEEKDAY_WAKE_MINUTE=30
WEEKEND_WAKE_HOUR=10
WEEKEND_WAKE_MINUTE=0

# === NOTIFICATIONS ===
SILENT_NOTIFICATIONS=true

# === EXTERNAL APIs (Optional) ===
TMDB_API_READ_TOKEN=your_tmdb_bearer_token
SONARR_URL=http://192.168.1.30:8989
SONARR_API_KEY=your_sonarr_api_key
RADARR_URL=http://192.168.1.30:7878
RADARR_API_KEY=your_radarr_api_key
EOF

# Add all files to git
git add .

# Make initial commit
git commit -m "Initial commit - Plex Telegram Bot

- Complete bot functionality with modular structure
- Plex and Jellyfin integration
- Sonarr/Radarr upcoming releases
- TMDB trending content
- Scheduled wake-on-LAN
- Weekly viewing statistics
- Silent notification support"

echo "✅ Git repository initialized!"
echo ""
echo "📝 Next steps:"
echo "1. Create a GitHub repository at github.com"
echo "2. Copy the remote URL from GitHub"
echo "3. Run: git remote add origin <your-github-url>"
echo "4. Run: git push -u origin main"
echo ""
echo "🔒 Important: Your .env file is excluded from git for security!"
EOF
