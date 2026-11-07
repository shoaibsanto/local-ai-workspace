"""Local-loopback OAuth redirect capture for MCP remote servers.

The MCP SDK's OAuth client needs a `redirect_handler` (opens the browser)
and expects the authorization code to come back on a redirect URI we
control. Since this is a local desktop app, we spin up a one-shot HTTP
server on localhost for the duration of a single authorization, exactly
like a CLI OAuth flow (gcloud, gh, etc.) — no public redirect URI, no
mandatory account with us.
"""

from __future__ import annotations

import asyncio
import webbrowser
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

from aiohttp import web


class OAuthCallbackServer:
    """Starts a loopback HTTP server, waits for exactly one
    `?code=...&state=...` redirect, then shuts down."""

    def __init__(self, port: int = 0):
        self.port = port
        self._future: asyncio.Future[tuple[str, str | None]] | None = None
        self._runner: web.AppRunner | None = None

    async def _handle(self, request: web.Request) -> web.Response:
        params = parse_qs(urlparse(str(request.url)).query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]

        if self._future and not self._future.done():
            if error:
                self._future.set_exception(RuntimeError(f"OAuth error: {error}"))
            elif code:
                self._future.set_result((code, state))
            else:
                self._future.set_exception(RuntimeError("No code in OAuth redirect"))

        return web.Response(
            text=(
                "<html><body style='font-family:sans-serif;text-align:center;"
                "padding-top:4rem'><h2>Authorization complete.</h2>"
                "<p>You can close this tab and return to the app.</p></body></html>"
            ),
            content_type="text/html",
        )

    async def start(self) -> int:
        app = web.Application()
        app.router.add_get("/callback", self._handle)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self.port)
        await site.start()
        actual_port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self.port = actual_port
        self._future = asyncio.get_event_loop().create_future()
        return int(actual_port)

    async def wait_for_code(self, timeout: float = 300) -> tuple[str, str | None]:
        assert self._future is not None
        try:
            return await asyncio.wait_for(self._future, timeout=timeout)
        finally:
            await self.stop()

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None


def make_redirect_handler(callback_server: OAuthCallbackServer) -> Callable:
    async def handler(authorization_url: str) -> None:
        webbrowser.open(authorization_url)

    return handler
