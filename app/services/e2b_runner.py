from typing import Dict, Any, Optional
from e2b import Sandbox
from app.core.config import settings
import structlog
import asyncio

logger = structlog.get_logger(__name__)


class E2BRunner:
    """
    Service for running code in E2B sandbox environment.
    Used by QA agent to test generated code.
    """
    
    def __init__(self):
        self.api_key = settings.e2b_api_key
    
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
        
        # Map language to E2B sandbox template
        template_map = {
            "python": "Python3",
            "javascript": "Node",
            "typescript": "Node",
            "bash": "Bash"
        }
        
        template = template_map.get(language.lower(), "Python3")
        
        with Sandbox(template=template, api_key=self.api_key, timeout=timeout) as sandbox:
            try:
                # Execute code
                execution = sandbox.run_code(code)
                
                return {
                    "success": execution.exit_code == 0,
                    "stdout": execution.stdout,
                    "stderr": execution.stderr,
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
            entrypoint: Main file to execute
            language: Programming language
            timeout: Execution timeout in seconds
        
        Returns:
            Dict with execution results
        """
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
        
        template_map = {
            "python": "Python3",
            "javascript": "Node",
            "typescript": "Node",
        }
        
        template = template_map.get(language.lower(), "Python3")
        
        with Sandbox(template=template, api_key=self.api_key, timeout=timeout) as sandbox:
            try:
                # Write all files to sandbox
                for filepath, content in files.items():
                    sandbox.filesystem.write(filepath, content)
                
                dependency_logs = []
                
                # CRITICAL: Install Python dependencies if requirements.txt exists
                if "requirements.txt" in files and language.lower() == "python":
                    logger.info("Installing Python dependencies from requirements.txt")
                    
                    pip_install = sandbox.run_code("pip install -r requirements.txt")
                    dependency_logs.append(f"[pip install]\n{pip_install.stdout}\n{pip_install.stderr}")
                    
                    if pip_install.exit_code != 0:
                        logger.warning(
                            "Dependency installation had issues",
                            exit_code=pip_install.exit_code,
                            stderr=pip_install.stderr[:200]
                        )
                
                # CRITICAL: Install Node dependencies if package.json exists
                if "package.json" in files and language.lower() in ["javascript", "typescript"]:
                    logger.info("Installing Node dependencies from package.json")
                    
                    npm_install = sandbox.run_code("npm install")
                    dependency_logs.append(f"[npm install]\n{npm_install.stdout}\n{npm_install.stderr}")
                    
                    if npm_install.exit_code != 0:
                        logger.warning(
                            "NPM installation had issues",
                            exit_code=npm_install.exit_code,
                            stderr=npm_install.stderr[:200]
                        )
                
                # Execute entrypoint
                if language.lower() == "python":
                    execution = sandbox.run_code(f"python {entrypoint}")
                elif language.lower() in ["javascript", "typescript"]:
                    execution = sandbox.run_code(f"node {entrypoint}")
                else:
                    execution = sandbox.run_code(entrypoint)
                
                # Combine dependency logs with execution output
                full_stdout = "\n".join(dependency_logs) + "\n" + execution.stdout if dependency_logs else execution.stdout
                
                return {
                    "success": execution.exit_code == 0,
                    "stdout": full_stdout,
                    "stderr": execution.stderr,
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
