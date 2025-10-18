"""
Launch script for Clinical Pediatric Nutrition RAG Chatbot (Gradio UI)

Usage:
    python launch_gradio.py
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from app.gradio_app import app

if __name__ == "__main__":
    print("=" * 80)
    print("Clinical Pediatric Nutrition Assistant - Gradio UI")
    print("=" * 80)
    print("\nStarting Gradio server...")
    print("Access the UI at: http://localhost:7860")
    print("\nPress Ctrl+C to stop the server\n")
    print("=" * 80)

    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,  # Set to True to create public shareable link
        show_error=True,
        quiet=False
    )
