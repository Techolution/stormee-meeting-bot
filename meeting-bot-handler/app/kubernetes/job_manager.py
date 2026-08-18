"""
Kubernetes Job lifecycle management.
"""


class KubernetesJobManager:
    async def create_job(self, *args, **kwargs):
        raise NotImplementedError

    async def get_job(self, *args, **kwargs):
        raise NotImplementedError

    async def delete_job(self, *args, **kwargs):
        raise NotImplementedError

    async def get_job_status(self, *args, **kwargs):
        raise NotImplementedError
