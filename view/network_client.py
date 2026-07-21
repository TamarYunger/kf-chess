from __future__ import annotations

import asyncio
import json
import queue
import threading

import websockets
import websockets.exceptions

DEFAULT_RECONNECT_DELAY_SECONDS = 2.0


class NetworkClient:
    """Runs a WebSocket connection on its own background thread.

    The graphical render loop (view/img.py, driven by cv2.waitKey) is
    synchronous and must never block on network I/O, so the actual
    `websockets` connection - and the asyncio event loop it needs - lives
    entirely on a dedicated thread. Every message received there is
    JSON-decoded and pushed onto a thread-safe `queue.Queue`; the render
    loop calls `drain()` once per frame to pop whatever has arrived so far,
    without blocking.

    Every message put on the queue is a dict shaped `{"type": ..., "payload":
    ...}`. Besides whatever the server sends, this client emits its own
    connection-lifecycle events the same way: "connected", "disconnected",
    "connection_error" (payload `{"error": str}`) - so a screen (e.g. a
    future login screen) can react to connectivity without polling.
    """

    def __init__(self, url, incoming=None, reconnect_delay=DEFAULT_RECONNECT_DELAY_SECONDS,
                 close_timeout=10, open_timeout=10):
        self._url = url
        self.incoming = incoming if incoming is not None else queue.Queue()
        self._reconnect_delay = reconnect_delay
        # Exposed mainly so tests can shrink the closing handshake instead of
        # waiting out websockets' real-world defaults on every stop().
        self._close_timeout = close_timeout
        self._open_timeout = open_timeout
        self._loop = None
        self._thread = None
        self._task = None
        self._connection = None
        # Set once _run() has assigned self._loop/self._task, on the
        # background thread - stop() must not act on either before then.
        # Without this, calling stop() right after start() (there is
        # nothing unusual about that timing - it's just two calls with no
        # work in between) can race the thread's own startup: self._loop/
        # self._task are still None, so stop() would silently skip
        # cancelling anything and fall straight through to a useless 5s
        # join() timeout, leaking a connection attempt that runs forever.
        self._ready = threading.Event()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread is None:
            return  # start() was never called - nothing to wait for or cancel
        if self._ready.wait(timeout=5) and self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)
        self._thread.join(timeout=5)

    def send(self, message):
        """Thread-safe: schedules `message` (a JSON-able dict) to be sent on
        the network thread. Silently dropped while not connected - callers
        that care should watch for "connected"/"disconnected" instead of
        relying on this raising."""
        if self._loop is None or self._connection is None:
            return
        asyncio.run_coroutine_threadsafe(self._send_async(message), self._loop)

    async def _send_async(self, message):
        connection = self._connection
        if connection is not None:
            await connection.send(json.dumps(message))

    def drain(self):
        """Pops every message currently queued, without blocking - for the
        render loop to call once per frame."""
        messages = []
        while True:
            try:
                messages.append(self.incoming.get_nowait())
            except queue.Empty:
                break
        return messages

    # -- background thread -------------------------------------------------

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self._connect_loop())
        self._ready.set()
        try:
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        finally:
            self._loop.close()

    async def _connect_loop(self):
        while True:
            try:
                async with websockets.connect(
                    self._url, open_timeout=self._open_timeout, close_timeout=self._close_timeout,
                ) as connection:
                    self._connection = connection
                    self.incoming.put({"type": "connected", "payload": None})
                    async for raw in connection:
                        self.incoming.put(json.loads(raw))
                    self.incoming.put({"type": "disconnected", "payload": None})
            except asyncio.CancelledError:
                raise
            except (OSError, websockets.exceptions.WebSocketException) as error:
                self.incoming.put({"type": "connection_error", "payload": {"error": str(error)}})
            finally:
                self._connection = None
            await asyncio.sleep(self._reconnect_delay)
