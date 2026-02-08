"""Docker agent worker for sandboxed code execution."""

from __future__ import annotations

import os
import asyncio
import tempfile
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum


class ExecutionLanguage(Enum):
    """Supported execution languages."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    BASH = "bash"


@dataclass
class ExecutionResult:
    """Result of code execution."""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: float
    memory_usage_mb: Optional[float] = None


@dataclass
class ExecutionRequest:
    """Request to execute code."""
    code: str
    language: ExecutionLanguage
    timeout_seconds: int = 30
    memory_limit_mb: int = 256
    input_data: Optional[str] = None


class DockerAgentWorker:
    """
    Worker for executing code in Docker containers.
    
    This provides a sandboxed environment for running user code safely.
    In production, this would use the Docker SDK to manage containers.
    """
    
    def __init__(
        self,
        docker_image: str = "python:3.11-slim",
        network_disabled: bool = True,
    ):
        self.docker_image = docker_image
        self.network_disabled = network_disabled
        self.container_id: Optional[str] = None
    
    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """
        Execute code in a sandboxed Docker container.
        
        This is a simplified implementation. In production:
        1. Create a Docker container with resource limits
        2. Copy the code into the container
        3. Execute and capture output
        4. Clean up the container
        """
        # For development/testing without Docker
        if os.getenv("DISABLE_DOCKER_AGENT", "false").lower() == "true":
            return await self._execute_local(request)
        
        return await self._execute_docker(request)
    
    async def _execute_local(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute code locally (for development only)."""
        import time
        start_time = time.time()
        
        try:
            if request.language == ExecutionLanguage.PYTHON:
                result = await self._run_python(request.code, request.timeout_seconds)
            elif request.language == ExecutionLanguage.JAVASCRIPT:
                result = await self._run_javascript(request.code, request.timeout_seconds)
            elif request.language == ExecutionLanguage.BASH:
                result = await self._run_bash(request.code, request.timeout_seconds)
            else:
                return ExecutionResult(
                    success=False,
                    stdout="",
                    stderr=f"Unsupported language: {request.language}",
                    exit_code=1,
                    execution_time_ms=0,
                )
            
            execution_time = (time.time() - start_time) * 1000
            return ExecutionResult(
                success=result["exit_code"] == 0,
                stdout=result["stdout"],
                stderr=result["stderr"],
                exit_code=result["exit_code"],
                execution_time_ms=execution_time,
            )
        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="Execution timed out",
                exit_code=-1,
                execution_time_ms=request.timeout_seconds * 1000,
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=1,
                execution_time_ms=(time.time() - start_time) * 1000,
            )
    
    async def _run_python(self, code: str, timeout: int) -> Dict[str, Any]:
        """Run Python code."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            temp_path = f.name
        
        try:
            proc = await asyncio.create_subprocess_exec(
                "python", temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode or 0,
            }
        finally:
            os.unlink(temp_path)
    
    async def _run_javascript(self, code: str, timeout: int) -> Dict[str, Any]:
        """Run JavaScript code using Node.js."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(code)
            f.flush()
            temp_path = f.name
        
        try:
            proc = await asyncio.create_subprocess_exec(
                "node", temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode or 0,
            }
        finally:
            os.unlink(temp_path)
    
    async def _run_bash(self, code: str, timeout: int) -> Dict[str, Any]:
        """Run Bash code."""
        proc = await asyncio.create_subprocess_shell(
            code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode or 0,
        }
    
    async def _execute_docker(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute code in Docker container."""
        # Placeholder for Docker execution
        # In production, this would use docker-py or subprocess to run Docker
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="Docker execution not implemented in development mode",
            exit_code=1,
            execution_time_ms=0,
        )


async def execute_code(
    code: str,
    language: str = "python",
    timeout_seconds: int = 30,
) -> ExecutionResult:
    """Convenience function to execute code."""
    try:
        lang = ExecutionLanguage(language.lower())
    except ValueError:
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=f"Unsupported language: {language}",
            exit_code=1,
            execution_time_ms=0,
        )
    
    worker = DockerAgentWorker()
    request = ExecutionRequest(
        code=code,
        language=lang,
        timeout_seconds=timeout_seconds,
    )
    return await worker.execute(request)
