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
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Call LLM chat completion endpoint.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model identifier (e.g., 'gpt-4', 'claude-3-opus')
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
                **kwargs
            )
            
            # Convert ModelResponse to dict
            response_dict = response.model_dump()
            
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
        model: str = "gpt-4",
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
        
        return response["choices"][0]["message"]["content"]


# Global LLM router instance
llm_router = LLMRouter()
