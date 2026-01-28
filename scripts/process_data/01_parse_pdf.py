#!/usr/bin/env python3
"""
Step 1: Parse PDF book using LlamaParse and save to cache.

Extracts text from PDF pages and saves as JSON for further processing.

Usage:
    # Quick mode - just specify book name:
    python scripts/process_data/01_parse_pdf.py \
        --name "1 Приемы педагогической техники" \
        --subdir andragogy

    # Explicit paths:
    python scripts/process_data/01_parse_pdf.py \
        --pdf data/books/book.pdf \
        --output data/cache/book_parsed.json

Environment:
    LLAMA_CLOUD_API_KEY: LlamaParse API key
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data import parse_and_save


def main():
    parser = argparse.ArgumentParser(
        description="Parse PDF book using LlamaParse and save to cache"
    )
    
    # Quick mode
    parser.add_argument(
        "--name",
        help="Book name (without extension). Auto-generates paths."
    )
    parser.add_argument(
        "--subdir",
        default="",
        help="Subdirectory in data/books/ (e.g., 'andragogy')"
    )
    
    # Explicit paths
    parser.add_argument("--pdf", help="Path to PDF file")
    parser.add_argument("--output", help="Output path for parsed JSON")
    
    # Options
    parser.add_argument(
        "--language",
        default="ru",
        help="Document language (default: ru)"
    )
    
    args = parser.parse_args()
    
    # Handle --name shortcut
    if args.name:
        subdir_path = f"{args.subdir}/" if args.subdir else ""
        args.pdf = f"data/books/{subdir_path}{args.name}.pdf"
        args.output = f"data/cache/{args.name}_parsed.json"
    
    if not args.pdf or not args.output:
        parser.print_help()
        print("\nError: Specify --name or --pdf/--output")
        sys.exit(1)
    
    # Check if PDF exists
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: PDF file not found: {args.pdf}")
        sys.exit(1)
    
    # Check if output already exists
    output_path = Path(args.output)
    if output_path.exists():
        print(f"Output already exists: {args.output}")
        response = input("Overwrite? [y/N]: ").strip().lower()
        if response != 'y':
            print("Aborted.")
            sys.exit(0)
    
    print(f"{'='*60}")
    print("Step 1: Parsing PDF with LlamaParse")
    print(f"{'='*60}")
    print(f"PDF: {args.pdf}")
    print(f"Output: {args.output}")
    print(f"Language: {args.language}")
    print(f"{'='*60}")
    
    # Parse and save
    parsed_pages = parse_and_save(
        file_path=args.pdf,
        output_path=args.output,
        language=args.language,
    )
    
    print(f"\n{'='*60}")
    print(f"Done! Parsed {len(parsed_pages)} pages")
    print(f"Output: {args.output}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
