# ADR 0001: Bot Handler as Control Plane

The meeting-bot-handler is a control-plane service.

The existing meeting-bot repository remains responsible for actual
meeting execution.

The Handler owns Kubernetes lifecycle and command routing.
