# Kubernetes

## How a meeting reaches a pod

The bot runs as a Deployment of interchangeable pods. A meeting is *not*
interchangeable: it lives on one specific pod, and only that pod can stop its
recording or report its status. So the handler does not route through the bot's
load-balanced Service — it discovers pods and addresses one of them directly.

```
      POST /bot-sessions/{id}/start
                  |
                  v
          BotServiceResolver
                  |
                  v
            BotPodPool ---- list pods (Kubernetes API, label selector)
                  |
                  +-------- GET /api/meet/ready on each pod
                  |             200 = free   503 = in a meeting
                  v
        candidates, free first
                  |
                  v
        POST /api/meet/meetings/join  --> first pod that accepts
                  |
                  v
     session.service_url = http://<pod-ip>:5000
                  |
                  v
   every later command for this session goes to that pod
```

A bot pod fails its readiness probe while it is in a meeting. That is what makes
allocation possible: readiness *is* the free/busy signal.

Between the probe and the join another handler replica can claim the same pod.
That race is expected and handled — the pod answers `409
meeting_already_active`, and the handler moves to the next candidate. Only a pod
that actually accepts the join gets written to the session.

## What the handler needs from the cluster

| Requirement | Where |
|---|---|
| `get`, `list`, `watch` on pods in the bot namespace | `deploy/k8s/rbac.yaml` |
| `BOT_LABEL_SELECTOR` matching the bot pod template labels | `deploy/k8s/configmap.yaml` |
| `BOT_NAMESPACE` set to where the bot pods run | `deploy/k8s/configmap.yaml` |
| `BOT_POD_PORT` = the bot's `containerPort` (5000), not the Service port | `deploy/k8s/configmap.yaml` |

Pod IPs are directly routable within a GKE cluster, which is what makes
addressing a pod without a per-session Service work.

## Deploying

```bash
kubectl apply -f deploy/k8s/serviceaccount.yaml
kubectl apply -f deploy/k8s/rbac.yaml          # must land in the BOT namespace
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/deployment.yaml
kubectl apply -f deploy/k8s/service.yaml
```

If the handler and the bots run in different namespaces, apply `rbac.yaml` to
the bot namespace and leave the RoleBinding subject pointing at the handler's
namespace.

## Checking that discovery works

```bash
kubectl port-forward svc/meeting-bot-handler 8000:80
curl localhost:8000/bot-pods
```

```json
{
  "namespace": "default",
  "label_selector": "app.kubernetes.io/name=meeting-bot",
  "discovery_available": true,
  "total": 3,
  "free": 2,
  "pods": [
    {"name": "meeting-bot-7d9f-abc", "ip": "10.4.1.7", "base_url": "http://10.4.1.7:5000", "ready": true},
    {"name": "meeting-bot-7d9f-def", "ip": "10.4.2.3", "base_url": "http://10.4.2.3:5000", "ready": true},
    {"name": "meeting-bot-7d9f-ghi", "ip": "10.4.1.9", "base_url": "http://10.4.1.9:5000", "ready": false}
  ]
}
```

This is the first thing to look at when a dispatch fails.

| Symptom | Cause |
|---|---|
| `discovery_available: false` | No RBAC, or the handler is not running in a cluster. `detail` says which. |
| `total: 0` | `BOT_LABEL_SELECTOR` or `BOT_NAMESPACE` does not match the bot Deployment. |
| `total > 0`, all `ready: false` | Every pod is in a meeting. Scale the bot Deployment. |
| Pods listed but `ready: null` | The pod did not answer its probe — wrong `BOT_POD_PORT`, or the bot is still starting. |

`GET /ready` on the handler returns 503 when neither pod discovery nor a static
`BOT_SERVICE_URL` can produce a destination, which keeps traffic off a handler
that cannot dispatch anywhere.

## Running outside the cluster

Point the handler at one pod and skip discovery:

```bash
kubectl port-forward pod/meeting-bot-7d9f-abc 5000:5000
KUBERNETES_ENABLED=false BOT_SERVICE_URL=http://localhost:5000 make run
```

With a kubeconfig, discovery also works from a laptop — leave
`KUBERNETES_ENABLED=true` and the client falls back from in-cluster credentials
to `~/.kube/config`. Pod IPs are usually not routable from outside the cluster,
so dispatch will find pods it cannot reach; port-forwarding is the reliable
route.

## Jobs versus a Deployment

`docs/adr/0001-control-plane.md` and the earlier `KubernetesJobManager` sketch
assumed one Job per meeting. The bot is deployed as a long-running Deployment
instead, and pods are allocated from that pool. A Job per meeting pays Chromium
startup on every join and needs a Service per session to be addressable; pooling
avoids both. `app/kubernetes/job_manager.py` and `service_manager.py` remain
unimplemented stubs for the day that trade-off changes.
