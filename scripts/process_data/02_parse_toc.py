#!/usr/bin/env python3
"""
Step 2: Parse table of contents from text file using Yandex Cloud LLM.

Converts raw TOC text (copied from PDF) into structured JSON format.

Usage:
    python scripts/process_data/02_parse_toc.py toc.txt > data/toc/book_name_toc.json

Environment:
    YC_API_KEY: Yandex Cloud API key
    YC_FOLDER_ID: Yandex Cloud folder ID
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load .env from project root
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)


SYSTEM_PROMPT = """You are a helpful assistant that parses book table of contents into structured JSON format.

Your task is to analyze the raw TOC text and convert it into a hierarchical JSON structure with book metadata.

Rules:
1. Extract book metadata: author, title, and year (if available)
2. Identify parts, chapters, sections, and subsections from the text
3. Roman numerals (I, II, III) or words like "Часть", "Part" usually indicate major parts
4. Numbers or "Глава", "Chapter" usually indicate chapters
5. Nested items should be grouped under their parent using recursive "children" arrays
6. Extract page numbers from the text and store them in "page" field (as integer)
7. Page numbers should be REMOVED from titles (stored separately in "page" field)
8. Keep the original language of titles (Russian, English, etc.)
9. Preserve the hierarchical structure based on indentation and numbering
10. Each TOC item must have "title" (string), "page" (integer or null), and "children" (array) fields
11. The structure supports unlimited nesting depth
12. If page number is not available for an item, set "page" to null

Output format:
{
  "meta": {
    "author": "Author Name",
    "title": "Book Title"
  },
  "toc": [
    {
      "title": "Section Title",
      "page": 10,
      "children": [
        {
          "title": "Subsection Title",
          "page": 15,
          "children": []
        }
      ]
    }
  ]
}
"""

# Yandex Cloud API settings
YANDEX_ENDPOINT = "https://llm.api.cloud.yandex.net/v1/chat/completions"
DEFAULT_MODEL = "gemma-3-27b-it/latest"
TIMEOUT = 360


def parse_toc_with_yandex(toc_text: str, model: str = DEFAULT_MODEL) -> dict:
    """Parse raw TOC text into structured format using Yandex Cloud LLM."""
    api_key = os.getenv("YC_API_KEY")
    folder_id = os.getenv("YC_FOLDER_ID")
    
    if not api_key:
        raise ValueError("YC_API_KEY environment variable is not set")
    if not folder_id:
        raise ValueError("YC_FOLDER_ID environment variable is not set")
    
    model_uri = f"gpt://{folder_id}/{model}"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {api_key}",
        "x-folder-id": folder_id,
    }
    
    user_message = f"Parse this TOC into JSON with metadata (author, title) and hierarchical structure.\n\nTOC:\n{toc_text}"
    
    payload = {
        "model": model_uri,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.1,
        "max_tokens": 8000,
        "response_format": {"type": "json_object"},
    }
    
    print("Sending request to Yandex Cloud...", file=sys.stderr)
    
    response = requests.post(
        YANDEX_ENDPOINT,
        headers=headers,
        json=payload,
        timeout=TIMEOUT,
    )
    
    if response.status_code != 200:
        raise RuntimeError(f"Yandex API error {response.status_code}: {response.text}")
    
    data = response.json()
    
    if "choices" in data and data["choices"]:
        message = data["choices"][0].get("message", {})
        content = message.get("content", "")
        return json.loads(content)
    
    raise RuntimeError("Empty response from Yandex API")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <toc_file.txt> [model]")
        print(f"  model: Yandex Cloud model (default: {DEFAULT_MODEL})")
        sys.exit(1)
    
    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    
    model = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL
    
    toc_text = input_path.read_text(encoding="utf-8")
    result = parse_toc_with_yandex(toc_text, model=model)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
