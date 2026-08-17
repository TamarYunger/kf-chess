"""Runs the REST POST /login call on its own background thread, mirroring
network_client.NetworkClient's own reasoning exactly: the render loop
(view/img.py, driven by cv2.waitKey) is synchronous and must never block
on network I/O - not even for a single request that will usually return
in a few milliseconds, because "usually" isn't "always" (a slow/
overloaded API Gateway would otherwise freeze the whole window). Every
result (a token, or a rejection) is pushed onto a thread-safe queue.Queue,
same shape as NetworkClient's own incoming messages - drained once per
frame, see NetworkGameSession.tick().
"""
from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request

from bus.event_types import LOGIN_REJECTED
from client.session.queue_utils import drain_queue

AUTH_TOKEN_RECEIVED = "auth_token_received"


class LoginClient:
    def __init__(self, api_gateway_url: str, incoming: queue.Queue | None = None) -> None:
        self._login_url = api_gateway_url.rstrip("/") + "/login"
        self.incoming = incoming if incoming is not None else queue.Queue()

    def login(self, username: str, password: str) -> None:
        threading.Thread(target=self._login, args=(username, password), daemon=True).start()

    def _login(self, username: str, password: str) -> None:
        body = json.dumps({"username": username, "password": password}).encode("utf-8")
        request = urllib.request.Request(
            self._login_url, data=body, headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read())
            self.incoming.put({"type": AUTH_TOKEN_RECEIVED, "payload": payload})
        except urllib.error.HTTPError as error:
            message = json.loads(error.read())["message"]
            self.incoming.put({"type": LOGIN_REJECTED, "payload": {"message": message}})
        except (urllib.error.URLError, OSError) as error:
            self.incoming.put({"type": LOGIN_REJECTED, "payload": {"message": str(error)}})

    def drain(self) -> list[dict]:
        """Pops every message currently queued, without blocking - for
        NetworkGameSession.tick() to call once per frame, same contract as
        NetworkClient.drain()."""
        return drain_queue(self.incoming)
