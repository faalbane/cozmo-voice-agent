#!/usr/bin/env python3
"""Seed the ChromaDB knowledge base with company documents."""

import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from src.knowledge.ingest import ingest_all

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    count = ingest_all()
    print(f"Seeded knowledge base with {count} document chunks.")
