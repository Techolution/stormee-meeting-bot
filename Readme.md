
# Project Name: Stormee Meet Bot 🤖

This project is a powerful web automation and API service, built with **Python 3.12**, leveraging **Playwright** for robust browser interaction and **FastAPI** for core application routing.

## ⚙️ Project Structure

The codebase follows a clear Model-Controller-Service (MCS) architectural pattern, wrapped in an API structure.

| Path | Purpose |
| :--- | :--- |
| **`main.py`** | Application entry point (likely instantiates the FastAPI app). |
| **`controllers/`** | Contains high-level logic for handling API requests and delegating to services. |
| **`services/`** | **Core business logic**. Contains the `stormee_meet_bot_service.py` where Playwright automation logic resides. |
| **`routes/`** | Defines all API endpoints using FastAPI's routing (e.g., `/start_bot`). |
| **`extras/`** | Utility and configuration files, including testing and environment scripts. |
| **`Dockerfile`** | Defines the reproducible environment for containerized deployment. |
| **`run.sh`** | **The main script** for running the project via Docker. |
| **`requirements.txt`** | Lists all Python dependencies for local installation. |
| **`.gitignore`** | Specifies files and folders to ignore (e.g., `venv`, `__pycache__`). |

-----

## 🚀 Option 1: Local Setup with `uv` (Recommended for Development)

This approach creates an isolated environment using Python **3.12** and the fast package manager, **`uv`**.

### 1\. Prerequisites

1.  **Python 3.12**: Must be installed on your system.
2.  **`uv`**: Install `uv` for lightning-fast environment setup and dependency resolution.
    ```bash
    # Install uv (via standalone installer for best performance on Linux/macOS)
    curl -LsSf https://astral.sh/uv/install.sh | sh 
    # OR, if you use pipx
    # pipx install uv
    ```

### 2\. Installation Steps

1.  **Clone the Repository:**

    ```bash
    git clone https://github.com/your-username/stormee-meet-bot.git
    cd stormee-meet-bot
    ```

2.  **Create Virtual Environment and Install Dependencies:**
    `uv` will automatically detect and manage Python 3.12 as specified.

    ```bash
    # Create the virtual environment named 'venv'
    uv venv --python 3.12

    # Activate the environment
    source .venv/bin/activate

    # Install all dependencies from requirements.txt
    uv pip install -r requirements.txt
    ```

3.  **Install Playwright Browser Binaries:**
    Playwright requires the actual browser executables.

    ```bash
    playwright install
    ```

### 3\. Running Locally

With the virtual environment active, you can run the FastAPI application using the installed `uvicorn` server:

```bash
(venv) $ uvicorn main:app --reload
```

The Playwright code will execute within this FastAPI process when its endpoints are hit.

-----

## 🐳 Option 2: Containerized Execution with Docker

This method is highly recommended for production, CI/CD, or for running the bot on systems without direct Playwright dependencies installed. The provided **`run.sh`** script handles the entire process.

### 1\. Prerequisites

  * **Docker Engine**: Must be installed and running.
  * **`Dockerfile`**: Defines the project's isolated environment.

### 2\. Execution Script (`run.sh`)

The `run.sh` script automates the Docker build and run sequence.

1.  **Grant Execution Permissions:**

    ```bash
    chmod +x run.sh
    ```

2.  **Run the Project:**
    Execute the script. The script should be designed to handle building the Docker image based on the local code and then starting the service inside the container.

    ```bash
    ./run.sh
    ```

### Example Docker Command (Inside `run.sh`)

For context, your `run.sh` likely executes a command sequence similar to this:

```bash
# 1. Build the Docker Image (replace your-image-name)
docker build -t stormee-bot-image .

# 2. Run the Container
# Important flags: --ipc=host is critical for Playwright/Chromium stability.
docker run \
    --rm \
    --name stormee-meet-bot-instance \
    --init \
    --ipc=host \
    -p 8000:8000 \
    stormee-bot-image 
```

*(This assumes your application runs on port 8000 and needs access to the host machine via IPC for Playwright to function correctly.)*

-----

## 🛠️ Testing and Utilities

The `extras/` directory contains useful scripts for debugging and testing:

  * **`extras/config.py`**: Holds configuration settings (API keys, URLs, Playwright launch options, etc.).
  * **`extras/debug_bot.py`**: A standalone script for quick, non-API-dependent testing of the core Playwright functionality.
    *Run with: `uv run python extras/debug_bot.py`*
  * **`extras/system_test.py`**: Likely contains high-level end-to-end tests that hit the API routes to verify the entire system, including the underlying Playwright logic.
  * **`extras/quick_test.sh`**: A shell utility, possibly for rapidly hitting a local or containerized endpoint (e.g., using `curl`).