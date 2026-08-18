"""
Kubernetes Service lifecycle management.

One Bot session should have a stable internal endpoint rather than
routing commands directly to a Pod IP.
"""


class KubernetesServiceManager:
    async def create_service(self, *args, **kwargs):
        raise NotImplementedError

    async def get_service(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_service(self, *args, **kwargs):
        raise NotImplementedError
