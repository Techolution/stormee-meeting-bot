# ADR 0001: Bot Handler as Control Plane

The meeting-bot-handler is a control-plane service.

The existing meeting-bot repository remains responsible for actual
meeting execution.

The Handler owns Kubernetes lifecycle and command routing.

*Superseded in part by [ADR 0002](0002-pod-pool-dispatch.md): the handler
allocates pods from a running Deployment rather than creating a Job per
meeting.*
