# Meeting Bot Handler Architecture

The Meeting Bot Handler is the control-plane service responsible for:

- Bot session lifecycle
- Kubernetes Job creation
- Kubernetes Service creation
- session-to-workload mapping
- routing commands to Bot Pods
- Bot health monitoring
- Kubernetes Job/Pod monitoring
- Meeting API callbacks

It does NOT implement:

- Google Meet automation
- Playwright
- recording
- transcription
- WebSocket/audio processing

Those responsibilities belong to the `meeting-bot` repository.
