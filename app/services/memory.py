from typing import List, Dict, Any, Optional
from mem0 import Memory
from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__)


class MemoryService:
    """
    Wrapper around Mem0 for long-term RAG memory.
    Stores and retrieves user context, preferences, and conversation history.
    """
    
    def __init__(self):
        self._client: Optional[Memory] = None
    
    def _get_client(self) -> Memory:
        """Lazy initialization of Mem0 client."""
        if self._client is None:
            logger.info("Initializing Mem0 client...")
            
            # Configure Mem0 with Qdrant vector store
            # CRITICAL: Mem0 v0.0.8+ uses environment variable OPENAI_API_KEY
            import os
            os.environ["OPENAI_API_KEY"] = settings.openai_api_key
            if settings.openai_base_url:
                os.environ["OPENAI_BASE_URL"] = settings.openai_base_url
                logger.info("Mem0 using custom OpenAI base URL", url=settings.openai_base_url)
            
            config = {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "host": settings.qdrant_host,
                        "port": settings.qdrant_port,
                        "collection_name": settings.mem0_collection_name,
                    }
                },
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": "openai/qwen3-235b-a22b-2507",
                        "temperature": 0.1,
                    }
                },
                "embedder": {
                    "provider": "openai",
                    "config": {
                        "model": "text-embedding-3-small",
                    }
                }
            }
            
            self._client = Memory.from_config(config)
            logger.info("Mem0 client initialized successfully")
        
        return self._client
    
    async def add_memory(
        self,
        messages: List[Dict[str, str]],
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Add conversation to long-term memory.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            user_id: Unique user identifier
            metadata: Additional context metadata
        
        Returns:
            Dictionary with added memory results
        """
        try:
            client = self._get_client()
            
            # Convert messages to a single string for Mem0
            conversation_text = "\n".join([
                f"{msg['role']}: {msg['content']}" 
                for msg in messages
            ])
            
            # Mem0 uses 'data' parameter (string)
            result = client.add(
                data=conversation_text,
                user_id=user_id,
                metadata=metadata or {}
            )
            
            logger.info(
                "Memory added",
                user_id=user_id,
                num_messages=len(messages),
                result=result
            )
            
            return result
        
        except Exception as e:
            logger.error("Failed to add memory", error=str(e), user_id=user_id)
            # Don't raise - memory storage is not critical
            return {}
    
    async def search_memory(
        self,
        query: str,
        user_id: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search long-term memory for relevant context.
        
        Args:
            query: Search query (typically current user message)
            user_id: Unique user identifier
            limit: Maximum number of memories to retrieve
        
        Returns:
            List of relevant memory entries
        """
        try:
            client = self._get_client()
            
            results = client.search(
                query=query,
                user_id=user_id,
                limit=limit
            )
            
            logger.info(
                "Memory search completed",
                user_id=user_id,
                query_length=len(query),
                results_count=len(results)
            )
            
            return results
        
        except Exception as e:
            logger.error("Failed to search memory", error=str(e), user_id=user_id)
            # Return empty list on error to not block the request
            return []
    
    async def get_all_memories(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all memories for a specific user.
        
        Args:
            user_id: Unique user identifier
        
        Returns:
            List of all user memories
        """
        try:
            client = self._get_client()
            
            memories = client.get_all(user_id=user_id)
            
            logger.info(
                "Retrieved all memories",
                user_id=user_id,
                count=len(memories)
            )
            
            return memories
        
        except Exception as e:
            logger.error("Failed to get all memories", error=str(e), user_id=user_id)
            return []
    
    async def delete_memory(self, memory_id: str, user_id: str) -> bool:
        """Delete a specific memory entry."""
        try:
            client = self._get_client()
            client.delete(memory_id=memory_id, user_id=user_id)
            
            logger.info("Memory deleted", memory_id=memory_id, user_id=user_id)
            return True
        
        except Exception as e:
            logger.error("Failed to delete memory", error=str(e), memory_id=memory_id)
            return False


# Global memory service instance
memory_service = MemoryService()
