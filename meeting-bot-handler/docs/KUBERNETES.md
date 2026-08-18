# Kubernetes

The Handler creates one Kubernetes Job for each Bot session.

Each Bot session should also have a stable Kubernetes Service.

Do not persist or use Pod IP as the primary Bot routing mechanism.

Conceptually:

Meeting API
    |
    v
Bot Handler
    |
    +-- Kubernetes Job
    |
    +-- Kubernetes Service
             |
             v
          Bot Pod
