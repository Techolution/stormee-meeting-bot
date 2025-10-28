# gmeet-bot
## Overview

`gmeet-bot` is a tool designed to interact with Google Meet sessions programmatically. It provides APIs for managing meetings, recording sessions, and converting audio files to `.wav` format. The bot ensures that each meeting ID is unique to avoid conflicts.

## Prerequisites

- Install [FFmpeg](https://ffmpeg.org/) for audio file conversion to `.wav` format.
- Ensure you have `Node.js` and `npm` installed.

### Installing FFmpeg

#### macOS
1. Install Homebrew if not already installed:
    ```bash
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    ```
2. Install FFmpeg:
    ```bash
    brew install ffmpeg
    ```

#### Ubuntu/Debian
1. Update the package list:
    ```bash
    sudo apt update
    ```
2. Install FFmpeg:
    ```bash
    sudo apt install ffmpeg
    ```

#### Windows
1. Download the FFmpeg build from the [official website](https://ffmpeg.org/download.html).
2. Extract the downloaded file and add the `bin` folder to your system's PATH.

## Installation

1. Clone the repository:
    ```bash
    git clone https://github.com/your-username/gmeet-bot.git
    cd gmeet-bot
    ```

2. Install dependencies:
    ```bash
    npm install
    ```

3. Configure environment variables:
    - Create a `.env` file in the root directory.
    - Add required configurations such as API keys, database credentials, etc.

4. Start the application:
    ```bash
    npm start
    ```

## APIs


### Start Meeting Recording
### Sign In to Meeting

To sign in to a Google Meet session, use the following API:

```bash
curl --location 'http://localhost:3000/api/meet/signin' \
--header 'Content-Type: application/json' \
--data '{
    "meetingUrl": "https://meet.google.com/bcz-ahto-zzf"
}'
```

- Replace `https://meet.google.com/bcz-ahto-zzf` with the URL of the Google Meet session you want to join.
- The API will return a response indicating whether the sign-in was successful.
To start recording a meeting, use the following API:

```bash
curl --location 'http://localhost:3000/api/meet/record/start' \
--header 'Content-Type: application/json' \
--data '{
    "meetingId": "unique-meeting-id"
}'
```

- Replace `unique-meeting-id` with a unique value for each meeting to ensure no conflicts.
- The `meetingId` must be unique for every recording session.
- The API will return a response indicating whether the recording has started successfully.
## Notes

- **FFmpeg Requirement:** Ensure FFmpeg is installed and added to your system's PATH for audio conversion functionality.
- **Unique Meeting IDs:** Each meeting ID must be unique to prevent conflicts. The system generates unique IDs automatically.

## License

This project is licensed under the [MIT License](LICENSE). 