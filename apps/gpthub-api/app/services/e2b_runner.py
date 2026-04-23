from typing import Dict, Any, Optional
from e2b import Sandbox
from app.core.config import settings
import structlog
import asyncio
import re
import shlex

logger = structlog.get_logger(__name__)

# Only allow safe relative file paths as entrypoints (no shell metacharacters)
_SAFE_ENTRYPOINT_RE = re.compile(r'^[\w][\w.\-/]*$')


class E2BRunner:
    """
    Service for running code in E2B sandbox environment.
    Used by QA agent to test generated code.
    """
    
    def __init__(self):
        self.api_key = settings.e2b_api_key

    @staticmethod
    def _result_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return "".join(str(item) for item in value)
        return str(value)

    @staticmethod
    def _looks_like_python_server(code: str) -> bool:
        markers = ("FastAPI(", "uvicorn.run(", "app.run(", "Flask(", "web.run_app(")
        return any(marker in code for marker in markers)

    @staticmethod
    def _fastapi_smoke_command(entrypoint: str) -> str:
        return f"""python - <<'PY'
import importlib.util
import sys

entrypoint = {entrypoint!r}
spec = importlib.util.spec_from_file_location("sandbox_app_module", entrypoint)
if spec is None or spec.loader is None:
    print(f"Cannot load module from {{entrypoint}}")
    raise SystemExit(1)

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
app = getattr(module, "app", None)
if app is None:
    print("No FastAPI app object found in entrypoint")
    raise SystemExit(1)

routes = [getattr(route, "path", "") for route in getattr(app, "routes", [])]
print(f"Detected routes: {{routes}}")
if "/" not in routes:
    print("Route '/' not found in FastAPI app")
    raise SystemExit(1)
PY"""
    
    async def run_code(
        self,
        code: str,
        language: str = "python",
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute code in E2B sandbox.
        
        Args:
            code: Code to execute
            language: Programming language (python, javascript, bash)
            timeout: Execution timeout in seconds
        
        Returns:
            Dict with stdout, stderr, exit_code, and error info
        """
        if not self.api_key:
            logger.warning("E2B API key is not configured")
            return {
                "success": False,
                "stdout": "",
                "stderr": "E2B_API_KEY is not configured",
                "exit_code": -1,
                "error": "E2B_API_KEY is not configured"
            }

        try:
            logger.info("Starting E2B sandbox execution", language=language)
            
            # Run in thread pool to not block event loop
            result = await asyncio.to_thread(
                self._execute_sync,
                code,
                language,
                timeout
            )
            
            logger.info(
                "E2B execution completed",
                exit_code=result.get("exit_code"),
                has_stdout=bool(result.get("stdout")),
                has_stderr=bool(result.get("stderr"))
            )
            
            return result
        
        except Exception as e:
            logger.error("E2B execution failed", error=str(e))
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "error": str(e)
            }
    
    def _execute_sync(
        self,
        code: str,
        language: str,
        timeout: int
    ) -> Dict[str, Any]:
        """Synchronous E2B execution (called in thread pool)."""
        snippet_path = {
            "python": "/tmp/snippet.py",
            "javascript": "/tmp/snippet.js",
            "typescript": "/tmp/snippet.ts",
            "bash": "/tmp/snippet.sh",
            "sh": "/tmp/snippet.sh",
        }.get(language.lower(), "/tmp/snippet.py")

        with Sandbox(api_key=self.api_key, timeout=timeout) as sandbox:
            try:
                sandbox.files.write(snippet_path, code)

                if language.lower() == "python":
                    execution = sandbox.commands.run(f"python {shlex.quote(snippet_path)}", timeout=timeout)
                elif language.lower() in ["javascript", "typescript"]:
                    execution = sandbox.commands.run(f"node {shlex.quote(snippet_path)}", timeout=timeout)
                elif language.lower() in ["bash", "sh"]:
                    execution = sandbox.commands.run(f"bash {shlex.quote(snippet_path)}", timeout=timeout)
                else:
                    execution = sandbox.commands.run(f"python {shlex.quote(snippet_path)}", timeout=timeout)

                return {
                    "success": execution.exit_code == 0,
                    "stdout": self._result_text(execution.stdout),
                    "stderr": self._result_text(execution.stderr),
                    "exit_code": execution.exit_code,
                    "error": None
                }
            
            except Exception as e:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": str(e),
                    "exit_code": -1,
                    "error": str(e)
                }
    
    async def run_project(
        self,
        files: Dict[str, str],
        entrypoint: str,
        language: str = "python",
        timeout: int = 60
    ) -> Dict[str, Any]:
        """
        Run a multi-file project in E2B sandbox.
        
        Args:
            files: Dict mapping file paths to file contents
            entrypoint: Main file to execute (must be a safe relative path)
            language: Programming language
            timeout: Execution timeout in seconds
        
        Returns:
            Dict with execution results
        """
        if not self.api_key:
            logger.warning("E2B API key is not configured")
            return {
                "success": False,
                "stdout": "",
                "stderr": "E2B_API_KEY is not configured",
                "exit_code": -1,
                "error": "E2B_API_KEY is not configured"
            }

        if not _SAFE_ENTRYPOINT_RE.match(entrypoint):
            logger.error("Invalid entrypoint rejected", entrypoint=entrypoint)
            return {
                "success": False,
                "stdout": "",
                "stderr": "Invalid entrypoint path",
                "exit_code": -1,
                "error": "Invalid entrypoint path"
            }

        try:
            logger.info(
                "Starting E2B project execution",
                num_files=len(files),
                entrypoint=entrypoint
            )
            
            result = await asyncio.to_thread(
                self._execute_project_sync,
                files,
                entrypoint,
                language,
                timeout
            )
            
            return result
        
        except Exception as e:
            logger.error("E2B project execution failed", error=str(e))
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "error": str(e)
            }
    
    def _execute_project_sync(
        self,
        files: Dict[str, str],
        entrypoint: str,
        language: str,
        timeout: int
    ) -> Dict[str, Any]:
        """
        Synchronous multi-file project execution with dependency installation.
        
        Critical: Installs dependencies before running code to prevent ModuleNotFoundError.
        """

        with Sandbox(api_key=self.api_key, timeout=timeout) as sandbox:
            try:
                # Write all files to sandbox
                for filepath, content in files.items():
                    sandbox.files.write(filepath, content)
                
                dependency_logs = []
                
                # CRITICAL: Install Python dependencies if requirements.txt exists
                if "requirements.txt" in files and language.lower() == "python":
                    logger.info("Installing Python dependencies from requirements.txt")
                    
                    pip_install = sandbox.commands.run("pip install -r requirements.txt", timeout=timeout)
                    dependency_logs.append(
                        f"[pip install]\n{self._result_text(pip_install.stdout)}\n{self._result_text(pip_install.stderr)}"
                    )
                    
                    if pip_install.exit_code != 0:
                        logger.warning(
                            "Dependency installation had issues",
                            exit_code=pip_install.exit_code,
                            stderr=self._result_text(pip_install.stderr)[:200]
                        )
                
                # CRITICAL: Install Node dependencies if package.json exists
                if "package.json" in files and language.lower() in ["javascript", "typescript"]:
                    logger.info("Installing Node dependencies from package.json")
                    
                    npm_install = sandbox.commands.run("npm install", timeout=timeout)
                    dependency_logs.append(
                        f"[npm install]\n{self._result_text(npm_install.stdout)}\n{self._result_text(npm_install.stderr)}"
                    )
                    
                    if npm_install.exit_code != 0:
                        logger.warning(
                            "NPM installation had issues",
                            exit_code=npm_install.exit_code,
                            stderr=self._result_text(npm_install.stderr)[:200]
                        )
                
                # Execute entrypoint — path is pre-validated by run_project()
                if language.lower() == "python":
                    source = files.get(entrypoint, "")
                    py_compile = sandbox.commands.run(
                        f"python -m py_compile {shlex.quote(entrypoint)}",
                        timeout=timeout,
                    )
                    if py_compile.exit_code != 0:
                        execution = py_compile
                    elif "FastAPI(" in source:
                        # Avoid long-running uvicorn server processes in QA smoke stage.
                        execution = sandbox.commands.run(
                            self._fastapi_smoke_command(entrypoint),
                            timeout=timeout,
                        )
                    elif self._looks_like_python_server(source):
                        execution_stdout = self._result_text(py_compile.stdout)
                        if execution_stdout:
                            execution_stdout += "\n"
                        execution_stdout += "Server-style entrypoint detected, runtime launch skipped after syntax check."
                        return {
                            "success": True,
                            "stdout": "\n".join(dependency_logs) + "\n" + execution_stdout if dependency_logs else execution_stdout,
                            "stderr": self._result_text(py_compile.stderr),
                            "exit_code": 0,
                            "error": None,
                            "dependency_logs": dependency_logs
                        }
                    else:
                        execution = sandbox.commands.run(f"python {shlex.quote(entrypoint)}", timeout=timeout)
                elif language.lower() in ["javascript", "typescript"]:
                    execution = sandbox.commands.run(f"node {shlex.quote(entrypoint)}", timeout=timeout)
                else:
                    execution = sandbox.commands.run(entrypoint, timeout=timeout)
                
                # Combine dependency logs with execution output
                execution_stdout = self._result_text(execution.stdout)
                execution_stderr = self._result_text(execution.stderr)
                full_stdout = "\n".join(dependency_logs) + "\n" + execution_stdout if dependency_logs else execution_stdout
                
                return {
                    "success": execution.exit_code == 0,
                    "stdout": full_stdout,
                    "stderr": execution_stderr,
                    "exit_code": execution.exit_code,
                    "error": None,
                    "dependency_logs": dependency_logs
                }
            
            except Exception as e:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": str(e),
                    "exit_code": -1,
                    "error": str(e)
                }


# Global E2B runner instance
e2b_runner = E2BRunner()
