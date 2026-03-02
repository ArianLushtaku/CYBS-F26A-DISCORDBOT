# CYBS-F26A Discord Bot

This repository contains the source code for a specialized Discord bot designed for the CYBS-F26A class. The bot automates schedule management by integrating with an external iCalendar feed and provides a robust student verification system to manage server access.

## Features

*   **Automated Calendar Management**:
    *   Synchronizes with an external iCalendar (.ics) feed every 1.5 hours to fetch the latest class schedule.
    *   Automatically creates, updates, and deletes Discord Scheduled Events based on the calendar data.
    *   Maintains auto-updating pinned messages in a designated channel, displaying the current week's schedule and the next upcoming module.

*   **Student Verification System**:
    *   A secure, email-based verification process for new members.
    *   Users interact with the bot in a private ticket channel to find their name in the student database.
    *   A unique 6-digit verification code is sent to the student's official school email via the Gmail API.
    *   Upon successful verification, the user's nickname is set to their first name and last initial, and they are assigned a class-specific role (e.g., `Hold_A`, `Hold_B`).
    *   Unverified users are restricted from accessing most channels.

*   **Slash Commands**:
    *   Provides easy-to-use slash commands for students to view schedules and for administrators to manage the bot.

## Commands

### User Commands
*   `/skema [vis]` - Displays the schedule for today or the next upcoming class module.
*   `/uge [uge] [år]` - Shows the schedule for a specific week. If no week is specified, it displays the current or next relevant week's schedule.

### Administrator Commands
*   `/setup [channel]` - Sets the text channel where the bot will post and maintain the pinned calendar messages. This is the first step to configuring the bot on a new server.
*   `/sync` - Manually forces the bot to synchronize with the external iCalendar feed and update all Discord events and messages.
*   `/deletecalendar` - Deletes all Discord scheduled events created by the bot.

## Setup and Installation

### Prerequisites
*   Python 3.x
*   A running MongoDB instance
*   A Google Cloud project with the Gmail API enabled and OAuth 2.0 credentials (Client ID, Client Secret, and a Refresh Token).

### Configuration
1.  Clone the repository:
    ```bash
    git clone https://github.com/arianlushtaku/cybs-f26a-discordbot.git
    cd cybs-f26a-discordbot
    ```

2.  Install the required Python packages:
    ```bash
    pip install -r requirements.txt
    ```

3.  Create a `.env` file in the root directory and populate it with the necessary credentials. This file is used to store sensitive information securely.

    ```env
    # Discord Bot Token
    DISCORD_TOKEN="YOUR_DISCORD_BOT_TOKEN"

    # iCalendar URL
    CALENDER_URL="YOUR_ICALENDAR_FEED_URL"

    # MongoDB Connection URI
    MONGODB_URI="mongodb://user:password@host:port/"
    
    # Gmail API Credentials for email verification
    EMAIL_SENDER="your-email@gmail.com"
    GOOGLE_CLIENT_ID="YOUR_GOOGLE_CLIENT_ID"
    GOOGLE_CLIENT_SECRET="YOUR_GOOGLE_CLIENT_SECRET"
    GOOGLE_REFRESH_TOKEN="YOUR_GOOGLE_REFRESH_TOKEN"

    # Optional: Exclude bot from running on specific guild IDs (comma-separated)
    EXCLUDED_GUILD_IDS=""
    ```
    
### Database Preparation
The bot relies on a MongoDB database named `discord_bot` with the following collections:
*   `guild_state`: Stores server-specific configurations.
*   `studentNames`: Must be populated with student records for the verification system. Each document should contain a `name` and `mail` (or `email`) field.
*   `user_verification`: Stores the verification status of users.
*   `verification_codes`: Used temporarily during the email verification process.

### Running the Bot
Start the bot using the `main.py` script. The application uses `uvicorn` to run a FastAPI web server alongside the Discord bot client.

```bash
python main.py
```

## Usage
1.  **Invite the Bot**: Invite the bot to your Discord server with the appropriate permissions (Manage Events, Manage Roles, Manage Channels, Send Messages, etc.).
2.  **Initial Setup**: As a server administrator, run the `/setup` command and specify the channel where you want the calendar to be displayed.
    ```
    /setup channel:#your-calendar-channel
    ```
3.  **Verification**: New users will be guided through the verification process. They can start by reacting with ✅ in the `#verifikation` channel. The bot will create a private ticket channel to complete the process.
