"""
Pytest configuration - fixes imports for test modules.
"""
import sys
import os

# Add project root to path so tests can import from src/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
