"""
Backend startup script for the Nutrition RAG Chatbot Flask application.
Run this script to start the Flask server.
"""
import os
import sys

# Add project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from app.application import app
from app.config.config import DEBUG, PORT

if __name__ == '__main__':
    print("=" * 60)
    print("Starting Nutrition RAG Chatbot Backend Server")
    print("=" * 60)
    print(f"Server: http://localhost:{PORT}")
    print(f"API Docs: http://localhost:{PORT}/health")
    print(f"Debug Mode: {DEBUG}")
    print("=" * 60)
    print("\nPress CTRL+C to quit\n")

    # Run Flask development server
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=DEBUG,
        threaded=True
    )
