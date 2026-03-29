# src/server/middleware.py
"""Custom middleware for the Stock Tool Server."""

import json
import logging
from typing import Callable
from urllib.parse import parse_qs

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class MarkdownNegotiationMiddleware(BaseHTTPMiddleware):
    """Intercept API responses and convert JSON to Markdown when requested.

    Triggers on ``?format=markdown`` query param or ``Accept: text/markdown``.
    Only applies to paths starting with ``/api/``.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only consider /api/ paths
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        # Check if client wants markdown
        fmt_param = request.query_params.get("format", "").lower()
        accept_header = request.headers.get("accept", "")
        wants_md = fmt_param == "markdown" or "text/markdown" in accept_header

        if not wants_md:
            return await call_next(request)

        # Get the original response
        response = await call_next(request)

        # If already markdown (e.g. fact-pack endpoints), pass through
        ct = response.headers.get("content-type", "")
        if "text/markdown" in ct:
            return response

        # Only convert JSON responses
        if "application/json" not in ct:
            return response

        # Read response body
        body_chunks = []
        async for chunk in response.body_iterator:
            body_chunks.append(chunk)
        body = b"".join(body_chunks)

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Not valid JSON, return as-is
            return Response(content=body, status_code=response.status_code,
                            headers=dict(response.headers), media_type=ct)

        # Extract data field from REST envelope: {"code": 0, "data": {...}}
        data = payload.get("data", payload) if isinstance(payload, dict) else payload

        # Build title from endpoint path
        path_parts = request.url.path.strip("/").split("/")
        title = " ".join(p.replace("-", " ").title() for p in path_parts[1:] if p)

        from src.server.domain.response_contract import json_to_markdown
        md_content = json_to_markdown(data, title=title)

        return Response(content=md_content, media_type="text/markdown")


class JsonArgumentsFixMiddleware(BaseHTTPMiddleware):
    """
    Middleware to fix JSON-RPC arguments for MCP clients.

    Some MCP clients (like OpenClaw) may send arguments in a malformed format.
    This middleware intercepts MCP requests and normalizes the arguments field.

    Common issues this fixes:
    - arguments as string instead of object: {"arguments": "{\"key\": \"value\"}"}
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request and fix JSON-RPC arguments if needed."""

        # Only process MCP endpoint requests
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)

        # Only process POST requests with JSON body
        if request.method != "POST":
            return await call_next(request)

        # Read and parse the request body
        try:
            body = await request.body()
            if not body:
                return await call_next(request)

            data = json.loads(body)
            modified = False

            # Fix arguments if it's a string instead of an object
            if isinstance(data, dict) and "params" in data:
                params = data["params"]
                if isinstance(params, dict) and "arguments" in params:
                    args = params["arguments"]
                    if isinstance(args, str):
                        try:
                            # Try to parse the string as JSON
                            parsed_args = json.loads(args)
                            params["arguments"] = parsed_args
                            modified = True
                            logger.debug(f"Fixed string arguments: {args} -> {parsed_args}")
                        except json.JSONDecodeError:
                            # If it's not valid JSON, leave it as is
                            pass

            if modified:
                # Replace the request body with the fixed version
                new_body = json.dumps(data).encode("utf-8")

                # Create a new request with the modified body
                async def receive():
                    return {"type": "http.request", "body": new_body}

                request = Request(request.scope, receive)

        except json.JSONDecodeError:
            # If the body isn't valid JSON, pass through unchanged
            pass
        except Exception as e:
            logger.warning(f"Error in JsonArgumentsFixMiddleware: {e}")

        return await call_next(request)
