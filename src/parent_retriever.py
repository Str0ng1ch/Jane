"""
Parent Document Retriever.

Implements the Parent Document Retriever pattern:
- Searches by small child chunks (better vector search)
- Returns full parent chunks (better LLM context)
- Falls back to child chunks if parent is too large for LLM context
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional

from .embedder import YCEmbedder
from .qdrant_manager import QdrantManager


# Default max size for parent chunks (in characters)
# If parent exceeds this, child chunk is returned instead
DEFAULT_MAX_PARENT_SIZE = 15000  # ~4K tokens for Russian text


class ParentDocumentRetriever:
    """
    Retriever that searches child chunks and returns parent chunks.
    
    Implements the retrieve(query, top_k) interface expected by BaseRAGChecker.
    
    The Parent Document Retriever pattern stores two types of chunks:
    - Child chunks: Small pieces optimized for vector search (~800 chars)
    - Parent chunks: Full chapters/sections for complete LLM context
    
    Each child chunk has a `parent_id` linking to its parent.
    
    Example:
        >>> embedder = YCEmbedder()
        >>> manager = QdrantManager(config)
        >>> parent_index = load_parent_chunks("data/chunks")
        >>> retriever = ParentDocumentRetriever(embedder, manager, parent_index)
        >>> results = retriever.retrieve("роль третьих мест в городе", top_k=5)
    """
    
    def __init__(
        self,
        embedder: YCEmbedder,
        manager: QdrantManager,
        parent_index: Dict[str, Dict[str, Any]],
        max_parent_size: int = DEFAULT_MAX_PARENT_SIZE,
    ):
        """
        Initialize the retriever.
        
        Args:
            embedder: YCEmbedder instance for query embedding
            manager: QdrantManager for vector search
            parent_index: Dict mapping parent_id -> parent chunk data
            max_parent_size: Max characters for parent chunk. If exceeded,
                child chunk is returned instead. Default: 15000 (~4K tokens)
        """
        self.embedder = embedder
        self.manager = manager
        self.parent_index = parent_index
        self.max_parent_size = max_parent_size
    
    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        source_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search child chunks and return corresponding parent chunks.
        
        If a parent chunk exceeds max_parent_size, the child chunk is 
        returned instead (with metadata flag 'fallback_to_child': True).
        
        The search process:
        1. Embed the query using YCEmbedder (text-search-query variant)
        2. Search child chunks in Qdrant (retrieve top_k * 3 for deduplication)
        3. For each result, get the parent chunk via parent_id
        4. If parent is too large, use child chunk instead
        5. Deduplicate by parent_id and return top_k unique results
        
        Args:
            query: Search query text
            top_k: Number of unique parent chunks to return
            source_type: Filter by source type ("student" or "teacher")
            
        Returns:
            List of dicts with 'text', 'metadata', and 'score' keys
        """
        # Get query embedding
        query_vector = self.embedder.embed_query(query)
        
        # Search child chunks (get more to deduplicate)
        results = self.manager.search(
            query_vector=query_vector,
            k=top_k * 3,
            filter_source_type=source_type,
        )
        
        # Collect unique parent chunks (or child chunks as fallback)
        seen_parent_ids = set()
        chunks = []
        
        for result in results:
            parent_id = result.metadata.get("parent_id")
            
            if not parent_id or parent_id in seen_parent_ids:
                continue
            
            seen_parent_ids.add(parent_id)
            parent = self.parent_index.get(parent_id)
            
            if parent:
                parent_text = parent["text"]
                
                # Check if parent is too large for LLM context
                if len(parent_text) > self.max_parent_size:
                    # Fallback to child chunk
                    child_metadata = result.metadata.copy()
                    child_metadata["fallback_to_child"] = True
                    child_metadata["parent_size"] = len(parent_text)
                    
                    chunks.append({
                        "text": result.text,
                        "metadata": child_metadata,
                        "score": result.score,
                    })
                else:
                    # Use parent chunk
                    chunks.append({
                        "text": parent_text,
                        "metadata": parent["metadata"],
                        "score": result.score,
                    })
            
            if len(chunks) >= top_k:
                break
        
        return chunks
    
    def retrieve_with_children(
        self,
        query: str,
        top_k: int = 5,
        source_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search child chunks and return both parent and matched child.
        
        Useful when you need to highlight which part of the parent was matched.
        If parent is too large, 'parent' will be None and 'fallback_to_child' 
        will be True in the result.
        
        Args:
            query: Search query text
            top_k: Number of unique parent chunks to return
            source_type: Filter by source type ("student" or "teacher")
            
        Returns:
            List of dicts with 'parent', 'child', 'score', and optionally
            'fallback_to_child' keys
        """
        query_vector = self.embedder.embed_query(query)
        results = self.manager.search(
            query_vector=query_vector,
            k=top_k * 3,
            filter_source_type=source_type,
        )
        
        seen_parent_ids = set()
        combined_results = []
        
        for result in results:
            parent_id = result.metadata.get("parent_id")
            
            if not parent_id or parent_id in seen_parent_ids:
                continue
            
            seen_parent_ids.add(parent_id)
            parent = self.parent_index.get(parent_id)
            
            if parent:
                parent_text = parent["text"]
                
                # Check if parent is too large
                if len(parent_text) > self.max_parent_size:
                    combined_results.append({
                        "parent": None,
                        "child": {
                            "text": result.text,
                            "metadata": result.metadata,
                        },
                        "score": result.score,
                        "fallback_to_child": True,
                        "parent_size": len(parent_text),
                    })
                else:
                    combined_results.append({
                        "parent": {
                            "text": parent_text,
                            "metadata": parent["metadata"],
                        },
                        "child": {
                            "text": result.text,
                            "metadata": result.metadata,
                        },
                        "score": result.score,
                        "fallback_to_child": False,
                    })
            
            if len(combined_results) >= top_k:
                break
        
        return combined_results


def load_parent_chunks(parent_dir: str) -> Dict[str, Dict[str, Any]]:
    """
    Load all parent chunks from a directory and index by parent_id.
    
    Expects files named *_parent.json with structure:
    [
        {
            "text": "chunk content...",
            "metadata": {
                "chunk_id": "uuid...",
                "book_title": "...",
                ...
            }
        },
        ...
    ]
    
    Args:
        parent_dir: Path to directory with parent chunk JSON files
        
    Returns:
        Dict mapping chunk_id -> chunk data (with 'text' and 'metadata')
    """
    parent_path = Path(parent_dir)
    
    if not parent_path.exists():
        return {}
    
    parent_files = list(parent_path.glob("*_parent.json"))
    parent_index: Dict[str, Dict[str, Any]] = {}
    
    for file_path in parent_files:
        with open(file_path, "r", encoding="utf-8") as f:
            chunks = json.load(f)
        
        for chunk in chunks:
            parent_id = chunk.get("metadata", {}).get("chunk_id")
            if parent_id:
                parent_index[parent_id] = {
                    "text": chunk.get("text", chunk.get("page_content", "")),
                    "metadata": chunk.get("metadata", {}),
                }
    
    return parent_index

