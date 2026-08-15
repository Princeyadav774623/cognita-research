from locust import HttpUser, task, between


class ResearchPlatformUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def check_health(self):
        self.client.get("/health")

    @task(2)
    def check_root(self):
        self.client.get("/")

    @task(1)
    def test_unauthenticated_api_rejection(self):
        self.client.get("/api/history", name="/api/history [unauth guard]")
