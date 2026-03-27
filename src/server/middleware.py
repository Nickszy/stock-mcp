# src/server/middleware.py
"""Custom middleware for the Stock Tool Server."""

import json
import logging
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


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


class DataSourceMiddleware(BaseHTTPMiddleware):
    """Middleware to inject data source into request state.

    This allows all API endpoints to access the preferred data source
    via request headers or query parameters.

    Usage:
        - Query parameter: ?source=akshare
        - Header: X-Data-Source: akshare
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Try query parameter first
        source: Optional[str] = request.query_params.get("source")

        # Fall back to header
        if not source:
            source = request.headers.get("X-Data-Source")

        # Store in request state
        request.state.source = source

        response = await call_next(request)

        return response
