# app/routes/upload.py
import os
import io
from flask import Blueprint, request, jsonify
from app.common.logger import get_logger

bp = Blueprint("upload", __name__)
logger = get_logger(__name__)

UPLOAD_DIR = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

def _extract_text(file_storage):
    filename = file_storage.filename
    ext = (os.path.splitext(filename)[1] or "").lower()

    # TXT path
    if ext in [".txt", ".csv", ".md"]:
        return file_storage.read().decode(errors="ignore")

    # PDF path (optional)
    if ext == ".pdf":
        try:
            import PyPDF2  # optional dependency
            reader = PyPDF2.PdfReader(io.BytesIO(file_storage.read()))
            text = []
            for page in reader.pages:
                text.append(page.extract_text() or "")
            return "\n".join(text).strip()
        except Exception as e:
            logger.warning(f"PDF parsing failed: {e}")
            return ""

    # Fallback: no parsing
    return ""

@bp.route("/api/upload", methods=["POST"])
def upload():
    """
    Multipart form:
      file: <File>
    Returns extracted text (if possible).
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        f = request.files["file"]
        if not f or not f.filename:
            return jsonify({"error": "Invalid file"}), 400

        path = os.path.join(UPLOAD_DIR, f.filename)
        f.stream.seek(0)
        f.save(path)

        f.stream.seek(0)
        text = _extract_text(f)

        return jsonify({
            "file_name": f.filename,
            "extracted_text": text or "",
            "message": "Uploaded successfully."
        })
    except Exception as e:
        logger.error(f"/api/upload failed: {e}")
        return jsonify({"error": "Upload failed", "detail": str(e)}), 500
