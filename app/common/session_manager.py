# app/common/session_manager.py
"""
Thread-safe session manager with user isolation.
Fixes the critical issue of shared session state across all users.
"""
import threading
import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from app.common.logger import get_logger

logger = get_logger(__name__)

class SessionManager:
    """
    Thread-safe session manager that isolates user sessions.
    Uses session_id to track individual user conversations.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._sessions = {}
                    cls._instance._session_lock = threading.RLock()
                    cls._instance._session_timeout = timedelta(hours=24)
        return cls._instance

    def create_session(self, user_id: Optional[str] = None) -> str:
        """
        Create a new session and return session_id.
        If user_id is provided, it's stored for auditing.
        """
        with self._session_lock:
            session_id = str(uuid.uuid4())
            self._sessions[session_id] = {
                "session_id": session_id,
                "user_id": user_id,
                "created_at": datetime.utcnow(),
                "last_accessed": datetime.utcnow(),
                "slots": {},
                "_intent_lock": None,
                "_awaiting_slot": None,
                "_awaiting_question": None,
                "_retry_count": 0,
                "_awaiting_confirmation": False,
                "_pending_medications": [],
                "_medication_suggestions": [],
                "_meal_plan_consent": False,
                "_medication_cache": {},
            }
            logger.info(f"Created session {session_id} for user {user_id}")
            return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get session data by session_id.
        Returns None if session doesn't exist or expired.
        """
        with self._session_lock:
            if session_id not in self._sessions:
                logger.warning(f"Session {session_id} not found")
                return None

            session = self._sessions[session_id]

            # Check if session expired
            if datetime.utcnow() - session["last_accessed"] > self._session_timeout:
                logger.info(f"Session {session_id} expired, removing")
                del self._sessions[session_id]
                return None

            # Update last accessed time
            session["last_accessed"] = datetime.utcnow()
            return session

    def update_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update session data.
        Returns True if successful, False if session doesn't exist.
        """
        with self._session_lock:
            session = self.get_session(session_id)
            if not session:
                return False

            session.update(updates)
            return True

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.
        Returns True if successful, False if session doesn't exist.
        """
        with self._session_lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"Deleted session {session_id}")
                return True
            return False

    def cleanup_expired_sessions(self):
        """
        Remove all expired sessions.
        Should be called periodically (e.g., by a background task).
        """
        with self._session_lock:
            now = datetime.utcnow()
            expired = [
                sid for sid, sess in self._sessions.items()
                if now - sess["last_accessed"] > self._session_timeout
            ]
            for sid in expired:
                del self._sessions[sid]
                logger.info(f"Cleaned up expired session {sid}")
            return len(expired)

    def get_session_count(self) -> int:
        """Get total number of active sessions"""
        with self._session_lock:
            return len(self._sessions)

    def get_user_sessions(self, user_id: str) -> list:
        """Get all active sessions for a user"""
        with self._session_lock:
            return [
                sid for sid, sess in self._sessions.items()
                if sess.get("user_id") == user_id
            ]

# Global singleton instance
_session_manager = SessionManager()

def get_session_manager() -> SessionManager:
    """Get the global session manager instance"""
    return _session_manager
