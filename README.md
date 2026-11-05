# Discord Location Tracker Bot

Tracks real-time location from OwnTracks and displays it as a Discord bot status.

## Deploy to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add environment variable: `BOT_TOKEN` = your Discord bot token
4. Railway gives you a public URL — use it in OwnTracks as `https://your-app.railway.app/location`

## Optional env vars

- `CHANNEL_ID` — Discord channel ID for periodic location embeds
- `POST_INTERVAL_MINUTES` — How often to post to channel (default: 30)
- `SECRET_TOKEN` — Auth token for OwnTracks requests

## Bot commands

- `!location` — Show current location & miles
- `!resetmiles` — Reset session miles
- `!resettotal` — Reset all miles
