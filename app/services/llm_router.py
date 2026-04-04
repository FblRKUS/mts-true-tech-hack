from typing import List, Dict, Any, Optional
import litellm
from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__)

# Configure LiteLLM
litellm.set_verbose = settings.debug


class LLMRouter:
    """
    Wrapper around LiteLLM for routing requests to different LLM providers.
    Provides unified interface for calling OpenAI, Anthropic, etc.
    """
    
    def __init__(self):
        # Set API keys
        litellm.openai_key = settings.openai_api_key
        
        # CRITICAL: Set custom base URL if provided
        if settings.openai_base_url:
            litellm.api_base = settings.openai_base_url
            logger.info("Using custom OpenAI base URL", url=settings.openai_base_url)
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "openai/qwen3-235b-a22b-2507",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Call LLM chat completion endpoint.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model identifier (e.g., 'openai/qwen3-235b-a22b-2507', 'claude-3-opus')
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
            **kwargs: Additional arguments passed to litellm
        
        Returns:
            Response dict with choices, usage, etc.
        """
        try:
            logger.info(
                "Calling LLM",
                model=model,
                num_messages=len(messages),
                temperature=temperature
            )
            
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                api_base=settings.openai_base_url if settings.openai_base_url else None,
                **kwargs
            )
            
            # Ensure response is not None
            if response is None:
                raise ValueError("LLM returned None response")
            
            # Convert ModelResponse to dict
            response_dict = response.model_dump() if hasattr(response, 'model_dump') else dict(response)
            
            logger.info(
                "LLM response received",
                model=model,
                prompt_tokens=response_dict.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=response_dict.get("usage", {}).get("completion_tokens", 0)
            )
            
            return response_dict
        
        except Exception as e:
            logger.error("LLM call failed", error=str(e), model=model)
            raise
    
    async def generate_text(
        self,
        prompt: str,
        model: str = "openai/qwen3-235b-a22b-2507",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Simple text generation helper.
        
        Args:
            prompt: User prompt
            model: Model identifier
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
            system_prompt: Optional system message
        
        Returns:
            Generated text content
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        response = await self.chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        # Extract content with safety checks
        if not response:
            raise ValueError("Empty response from LLM")
        
        choices = response.get("choices", [])
        if not choices:
            raise ValueError("No choices in LLM response")
        
        message = choices[0].get("message", {})
        content = message.get("content", "")
        
        if not content:
            logger.warning("Empty content in LLM response", response=response)
        
        return content


# Global LLM router instance
llm_router = LLMRouter()
