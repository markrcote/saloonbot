# Discord Bot Setup

Step-by-step instructions for creating and configuring a Discord bot for SaloonBot.

## 1. Create a Discord Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application**.
3. Enter a name (e.g. "SaloonBot") and click **Create**.

## 2. Get the Bot Token

1. In the left sidebar, click **Bot**.
2. Click **Reset Token**, then copy and save the token securely. You will need it later.
   > **Warning:** Treat this token like a password. Never commit it to version control.

## 3. Enable Privileged Intents

Still on the **Bot** page, scroll down to **Privileged Gateway Intents** and enable:

- **Message Content Intent** — required for reading in-channel game commands (e.g. `bet 50`, `hit`, `stand`)

Click **Save Changes**.

## 4. Generate an Invite URL

1. In the left sidebar, click **OAuth2 → URL Generator**.
2. Under **Scopes**, check:
   - `bot`
   - `applications.commands`
3. Under **Bot Permissions**, check:
   - **View Channels**
   - **Send Messages**
   - **Send Messages in Threads**
   - **Embed Links**
   - **Read Message History**
4. Copy the generated URL at the bottom of the page.

## 5. Invite the Bot to Your Server

1. Paste the invite URL into your browser.
2. Select the server you want to add the bot to.
3. Click **Authorize** and complete the CAPTCHA.

## 6. Get Your Guild (Server) ID

1. Open Discord and go to **User Settings → Advanced**.
2. Enable **Developer Mode**.
3. Right-click your server name in the left sidebar and select **Copy Server ID**.
   Save this value — it is your guild ID.

## 7. Configure SaloonBot

The bot requires two pieces of configuration: the bot token and the guild ID(s).

### Option A: Text files (recommended for Docker deployments)

Create two files in the project root:

```
discord_token.txt   ← paste your bot token here
discord_guilds.txt  ← paste your guild ID here (comma-separated for multiple guilds)
```

These files are read by `docker-compose` via the `DISCORD_TOKEN_FILE` and `DISCORD_GUILDS_FILE` environment variables.

### Option B: Environment variables

```bash
export DISCORD_TOKEN="your-bot-token"
export DISCORD_GUILDS="your-guild-id"   # comma-separated for multiple guilds
```

## 8. Run the Bot

See `README.md` for full development and production run options. Quick start:

**Production (all services in Docker):**
```bash
docker compose up -d
```

**Bot only locally (server in Docker):**
```bash
export DISCORD_TOKEN="your-bot-token"
export DISCORD_GUILDS="your-guild-id"
./dev-bot.sh
```

## 9. Verify the Bot is Working

1. In your Discord server, type `/version` in any channel the bot can see.
2. The bot should respond with the current git SHA or version string.
3. Try `/wwname` to generate a random Old West name.
4. Try `/newgame` to start a blackjack game.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Bot is online but slash commands don't appear | `applications.commands` scope was not selected when inviting; re-invite with the correct URL |
| Bot can't read `bet`/`hit`/`stand` messages | **Message Content Intent** is not enabled in the Developer Portal |
| Bot goes offline immediately | Token is incorrect or the `DISCORD_TOKEN` / `discord_token.txt` is not set |
| Game embeds don't display | **Embed Links** permission is missing |
