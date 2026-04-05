"""Invocation backends for get_study_assignment smoke tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol
from urllib import error, request

import boto3
from botocore.exceptions import ClientError

import lambdas.get_study_assignment.handler as handler_module
from jobs.mirrorview.constants import DEFAULT_BUCKET
from lib.s3 import S3


class HandlerInvocationError(RuntimeError):
    """Raised when an invocation backend fails to produce a valid response."""

    def __init__(self, *, backend: str, message: str) -> None:
        super().__init__(f"[{backend}] {message}")


class HandlerInvoker(Protocol):
    """Common interface consumed by the shared smoke suite."""

    backend_name: str

    def invoke(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """Invoke get_study_assignment and return the decoded payload."""
        ...


class LocalHandlerInvoker:
    backend_name = "local"

    def __init__(
        self,
        *,
        region_name: str,
        user_assignments_table_name: str,
        study_assignment_counter_table_name: str,
    ) -> None:
        # Ensure local in-process handler points at smoke-test resources.
        handler_module.region_name = region_name
        handler_module.user_assignments_table_name = user_assignments_table_name
        handler_module.study_assignment_counter_table_name = study_assignment_counter_table_name
        handler_module.s3 = S3(bucket=DEFAULT_BUCKET, region_name=region_name)

    def invoke(self, event: Mapping[str, Any]) -> dict[str, Any]:
        try:
            response = handler_module.handler(dict(event), None)
        except Exception as exc:  # pragma: no cover - passthrough diagnostics
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"handler raised exception: {exc}",
            ) from exc

        if not isinstance(response, dict):
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"expected dict response, got {type(response)!r}",
            )
        return response


class DockerHandlerInvoker:
    backend_name = "docker"

    def __init__(self, *, invoke_url: str, timeout_seconds: float = 10.0) -> None:
        self._invoke_url = invoke_url
        self._timeout_seconds = timeout_seconds

    def invoke(self, event: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(dict(event)).encode("utf-8")
        req = request.Request(
            self._invoke_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                status = response.status
                payload_raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"HTTP {exc.code} from Lambda RIE endpoint: {detail}",
            ) from exc
        except error.URLError as exc:
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"failed to reach Lambda RIE endpoint at {self._invoke_url}: {exc}",
            ) from exc

        if status < 200 or status >= 300:
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"unexpected HTTP status {status} from Lambda RIE endpoint",
            )

        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError as exc:
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"response is not valid JSON: {payload_raw}",
            ) from exc

        if not isinstance(payload, dict):
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"expected dict payload, got {type(payload)!r}",
            )

        if "errorMessage" in payload:
            error_type = payload.get("errorType", "LambdaRuntimeError")
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"Lambda runtime error ({error_type}): {payload['errorMessage']}",
            )

        return payload


class ProdLambdaHandlerInvoker:
    backend_name = "prod"

    def __init__(
        self,
        *,
        region_name: str,
        function_name: str,
        qualifier: str | None = None,
    ) -> None:
        self._client = boto3.client("lambda", region_name=region_name)
        self._function_name = function_name
        self._qualifier = qualifier

    def invoke(self, event: Mapping[str, Any]) -> dict[str, Any]:
        invoke_kwargs: dict[str, Any] = {
            "FunctionName": self._function_name,
            "InvocationType": "RequestResponse",
            "Payload": json.dumps(dict(event)).encode("utf-8"),
        }
        if self._qualifier:
            invoke_kwargs["Qualifier"] = self._qualifier

        try:
            response = self._client.invoke(**invoke_kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "AccessDeniedException":
                raise HandlerInvocationError(
                    backend=self.backend_name,
                    message=(
                        f"lambda invoke denied (IAM): {exc}. "
                        "Grant the caller lambda:InvokeFunction on the target function."
                    ),
                ) from exc
            if code == "ResourceNotFoundException":
                raise HandlerInvocationError(
                    backend=self.backend_name,
                    message=(
                        f"lambda function not found: {exc}. "
                        "Check SMOKE_PROD_LAMBDA_NAME, AWS_REGION, and SMOKE_PROD_LAMBDA_QUALIFIER "
                        "if set."
                    ),
                ) from exc
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"lambda invoke request failed: {exc}",
            ) from exc
        except Exception as exc:  # pragma: no cover - unexpected transport errors
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"lambda invoke request failed: {exc}",
            ) from exc

        payload_raw = response["Payload"].read().decode("utf-8")
        status_code = int(response.get("StatusCode", 0))
        if status_code < 200 or status_code >= 300:
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"unexpected Lambda status code {status_code}: {payload_raw}",
            )

        if response.get("FunctionError"):
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"Lambda returned FunctionError={response['FunctionError']}: {payload_raw}",
            )

        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError as exc:
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"Lambda payload is not valid JSON: {payload_raw}",
            ) from exc

        if not isinstance(payload, dict):
            raise HandlerInvocationError(
                backend=self.backend_name,
                message=f"expected dict payload, got {type(payload)!r}",
            )

        return payload
