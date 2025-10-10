import os
import pickle
import re
from typing import List, Dict, Any
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader
from ebooklib import epub
from bs4 import BeautifulSoup
from pdf2image import convert_from_path
import pytesseract
import gc
from app.common.logger import get_logger
from app.config.config import DATA_PATH, CHUNK_SIZE, CHUNK_OVERLAP
from tqdm import tqdm
from app.components.chapter_extractor import extract_chapters_from_pdf
from app.components.metadata_enricher import enrich_documents

# Initialize logger
logger = get_logger(__name__)

# Path to save chunks
CHUNKS_CACHE_PATH = os.path.join(os.path.dirname(DATA_PATH), "cache", "chunks.pkl")
os.makedirs(os.path.dirname(CHUNKS_CACHE_PATH), exist_ok=True)

# Configure Tesseract
try:
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    logger.info("✅ Tesseract path configured successfully")
    try:
        available_languages = pytesseract.get_languages(config='')
        logger.info(f"🔤 Available Tesseract languages: {available_languages}")
        if 'fra' in available_languages:
            logger.info("✅ French language pack (fra) is installed")
        else:
            logger.warning("⚠️ French language pack (fra) is NOT installed")
    except Exception as e:
        logger.warning(f"⚠️ Could not check Tesseract languages: {str(e)}")
except Exception as e:
    logger.error(f"❌ Failed to set Tesseract path: {str(e)}")

# ---------------------------
# Food/state detection helpers
# ---------------------------
STATES = ["raw", "boiled", "fried", "roasted", "dried", "fermented", "cooked", "steamed"]

def detect_food_and_state(text: str):
    """Heuristic extraction of food name and preparation state from text."""
    if not text:
        return "unknown", "unknown"

    text_lower = text.lower()
    detected_state = "raw"
    for state in STATES:
        if state in text_lower:
            detected_state = state
            break

    # Try capture food name before state keyword
    for state in STATES:
        match = re.search(r"([a-z\s\-]+)\s+" + state, text_lower)
        if match:
            return match.group(1).strip(), detected_state

    # Fallback → first 2–3 words of first line
    first_line = text.splitlines()[0] if text else ""
    food_name = " ".join(first_line.split()[:3]).strip()
    return food_name, detected_state

# ---------------------------
# OCR extraction
# ---------------------------
def extract_text_ocr(file_path: str, max_pages=None) -> str:
    """OCR extraction with proper error handling and multi-language support"""
    logger.info(f"🔍 Processing {os.path.basename(file_path)} with OCR")

    try:
        total_pages = None
        try:
            from pdf2image.exceptions import PDFPageCountException
            total_pages = len(convert_from_path(file_path, first_page=1, last_page=1, fmt="jpeg"))
            logger.info(f"📄 Document has {total_pages} total pages")
        except Exception as e:
            logger.warning(f"⚠️ Could not determine total page count: {str(e)}")

        if max_pages is None or (total_pages and max_pages > total_pages):
            max_pages = total_pages

        pages = convert_from_path(file_path, dpi=300, first_page=1, last_page=max_pages)

        text = ""
        for i, page in enumerate(pages):
            if i % 10 == 0 or i == len(pages) - 1:
                logger.info(f"🔄 Processing page {i+1}/{len(pages)}")

            try:
                page_text = pytesseract.image_to_string(page, lang='eng+fra')
                text += page_text + "\n"
                continue
            except Exception:
                pass

            try:
                page_text = pytesseract.image_to_string(page, lang='eng')
                text += page_text + "\n"
                continue
            except Exception:
                pass

            try:
                page_text = pytesseract.image_to_string(page)
                text += page_text + "\n"
            except Exception as e:
                logger.warning(f"Page {i+1} OCR failed: {str(e)}")

        if not text.strip():
            logger.warning(f"⚠️ OCR produced empty text for {os.path.basename(file_path)}")

        return text.strip()
    except Exception as e:
        logger.error(f"❌ Critical OCR failure for {file_path}: {str(e)}")
        return None

# ---------------------------
# Document type detection
# ---------------------------
def detect_document_type(filename: str) -> str:
    """
    Detect document type from filename for chapter-aware extraction.

    Returns:
        - "shaw_2020": Clinical Paediatric Dietetics
        - "preterm_2013": Nutrition for the Preterm Neonate
        - "drug_nutrient": Handbook of Drug-Nutrient Interactions
        - "biochemistry": Integrative Human Biochemistry
        - "fct": Food Composition Table (use character-based chunking)
        - "unknown": Other documents (use character-based chunking)
    """
    filename_lower = filename.lower()

    # Clinical Paediatric Dietetics (Shaw 2020)
    if any(keyword in filename_lower for keyword in ["shaw", "clinical paediatric dietetics", "paediatric dietetics"]):
        return "shaw_2020"

    # Nutrition for the Preterm Neonate
    if any(keyword in filename_lower for keyword in ["preterm neonate", "koletzko", "preterm nutrition"]):
        return "preterm_2013"

    # Drug-Nutrient Interactions
    if any(keyword in filename_lower for keyword in ["drug-nutrient", "drug nutrient", "boullata"]):
        return "drug_nutrient"

    # Integrative Human Biochemistry
    if any(keyword in filename_lower for keyword in ["biochemistry", "integrative human", "biochem"]):
        return "biochemistry"

    # Food Composition Tables (various countries)
    fct_keywords = ["fct", "food composition", "kenya", "tanzania", "india", "korea",
                    "canada", "lesotho", "malawi", "zimbabwe", "usda", "nutritive value"]
    if any(keyword in filename_lower for keyword in fct_keywords):
        return "fct"

    return "unknown"


# ---------------------------
# PDF loader
# ---------------------------
def load_pdf_files(file_paths: List[str] = None) -> List[Document]:
    """Load PDFs and inject metadata"""
    documents = []
    pdf_dir = os.path.join(DATA_PATH)
    if not os.path.exists(pdf_dir):
        os.makedirs(pdf_dir, exist_ok=True)
        logger.warning(f"⚠️ PDF directory not found, created: {pdf_dir}")

    if file_paths is None:
        file_paths = [os.path.join(pdf_dir, f) for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")]
        if not file_paths:
            logger.warning(f"⚠️ No PDF files found in {pdf_dir}")
            return []

    logger.info(f"📂 Found {len(file_paths)} PDF files to process")

    for i, file_path in enumerate(file_paths):
        filename = os.path.basename(file_path)
        logger.info(f"📄 Processing file {i+1}/{len(file_paths)}: {filename}")

        # Detect document type
        doc_type = detect_document_type(filename)
        logger.info(f"🔍 Detected document type: {doc_type}")

        # Route to chapter-aware extraction for clinical texts
        if doc_type in ["shaw_2020", "preterm_2013", "drug_nutrient", "biochemistry"]:
            try:
                logger.info(f"📚 Using chapter-aware extraction for {filename}")
                chapter_docs = extract_chapters_from_pdf(file_path, doc_type)
                if chapter_docs:
                    # Enrich with clinical tags
                    enriched_docs = enrich_documents(chapter_docs, doc_type)
                    documents.extend(enriched_docs)
                    logger.info(f"✅ Loaded {len(enriched_docs)} chapters from {filename}")
                    gc.collect()
                    continue
                else:
                    logger.warning(f"⚠️ Chapter extraction returned no documents for {filename}")
            except Exception as e:
                logger.error(f"❌ Chapter extraction failed for {filename}: {str(e)}")
                logger.info(f"↩️ Falling back to standard page-based parsing")

        # Standard page-based parsing for FCTs and unknown documents
        # Native parsing first
        try:
            docs = PyPDFLoader(file_path).load()
            if docs and any(doc.page_content.strip() for doc in docs):
                valid_docs = [doc for doc in docs if doc.page_content.strip()]
                for doc in valid_docs:
                    food_name, food_state = detect_food_and_state(doc.page_content)
                    doc.metadata["food_name"] = food_name
                    doc.metadata["food_state"] = food_state
                    doc.metadata["country_table"] = filename.replace(".pdf", "")
                    doc.metadata["document_type"] = doc_type
                documents.extend(valid_docs)
                logger.info(f"✅ Loaded {len(valid_docs)} pages from PDF: {filename}")
                continue
        except Exception as e:
            logger.warning(f"⚠️ PyPDFLoader failed for {filename}: {str(e)}")

        # OCR fallback
        logger.info(f"🔍 Attempting OCR fallback for {filename}")
        ocr_text = extract_text_ocr(file_path)
        if ocr_text and len(ocr_text) > 100:
            food_name, food_state = detect_food_and_state(ocr_text)
            documents.append(Document(
                page_content=ocr_text,
                metadata={
                    "source": file_path,
                    "food_name": food_name,
                    "food_state": food_state,
                    "country_table": filename.replace(".pdf", "")
                }
            ))
            logger.info(f"✅ Loaded via OCR: {filename}")
        else:
            logger.error(f"❌ Failed to extract text from {filename}")

        gc.collect()

    logger.info(f"📊 Total documents loaded: {len(documents)}")
    return documents

# ---------------------------
# EPUB loader
# ---------------------------
def load_epubs() -> List[Document]:
    """Load EPUBs and inject metadata"""
    documents = []
    epub_dir = os.path.join(DATA_PATH)

    if not os.path.exists(epub_dir):
        return []

    for i, file in enumerate(os.listdir(epub_dir)):
        if not file.lower().endswith(".epub"):
            continue

        path = os.path.join(epub_dir, file)
        logger.info(f"📖 Processing EPUB {i+1}: {file}")

        try:
            book = epub.read_epub(path)
            text = ""
            for item in book.get_items():
                if item.get_type() == 9:  # DOCUMENT
                    try:
                        soup = BeautifulSoup(item.get_content(), "html.parser")
                        text += soup.get_text() + "\n"
                    except Exception as e:
                        logger.debug(f"EPUB item parse error: {str(e)}")

            if text.strip():
                food_name, food_state = detect_food_and_state(text)
                documents.append(Document(
                    page_content=text,
                    metadata={
                        "source": path,
                        "food_name": food_name,
                        "food_state": food_state,
                        "country_table": file.replace(".epub", "")
                    }
                ))
                logger.info(f"✅ Loaded EPUB: {file}")
        except Exception as e:
            logger.error(f"❌ EPUB loading failed for {file}: {str(e)}")

        gc.collect()

    return documents

# ---------------------------
# Chunking (chapter-aware routing)
# ---------------------------
def create_text_chunks(documents: List[Document], chunk_size=None, chunk_overlap=None) -> List[Document]:
    """
    Create text chunks with chapter-aware routing:
    - Clinical texts (already chunked as chapters): Return as-is
    - FCTs and unknown documents: Apply character-based chunking
    """
    if not documents:
        logger.warning("⚠️ No documents provided to chunk")
        return []

    if chunk_size is None:
        chunk_size = CHUNK_SIZE
    if chunk_overlap is None:
        chunk_overlap = CHUNK_OVERLAP

    # Separate chapter documents from page-based documents
    chapter_docs = [doc for doc in documents if doc.metadata.get("chunk_type") == "chapter"]
    page_docs = [doc for doc in documents if doc.metadata.get("chunk_type") != "chapter"]

    logger.info(f"📊 Document breakdown: {len(chapter_docs)} chapter documents, {len(page_docs)} page-based documents")

    # Chapter documents are already semantic units - keep as-is
    chunks = chapter_docs.copy()
    if chapter_docs:
        logger.info(f"✅ Kept {len(chapter_docs)} chapter documents as semantic units")

    # Apply character-based chunking to page documents (FCTs, unknown)
    if page_docs:
        logger.info(f"✂️ Creating text chunks for {len(page_docs)} page-based documents (size: {chunk_size}, overlap: {chunk_overlap})")
        try:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                length_function=len,
                is_separator_regex=False,
            )
            page_chunks = splitter.split_documents(page_docs)
            chunks.extend(page_chunks)
            logger.info(f"✂️ Created {len(page_chunks)} chunks from page-based documents")
        except Exception as e:
            logger.error(f"❌ Failed to create text chunks: {str(e)}")

    logger.info(f"📊 Total chunks: {len(chunks)} ({len(chapter_docs)} chapters + {len(chunks) - len(chapter_docs)} page chunks)")
    return chunks

def save_chunks_to_cache(chunks: List[Document]):
    try:
        with open(CHUNKS_CACHE_PATH, "wb") as f:
            pickle.dump(chunks, f)
        logger.info(f"✅ Chunks saved to cache: {CHUNKS_CACHE_PATH} ({len(chunks)} chunks)")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to save chunks to cache: {str(e)}")
        return False

def load_chunks_from_cache() -> List[Document]:
    if os.path.exists(CHUNKS_CACHE_PATH):
        try:
            with open(CHUNKS_CACHE_PATH, "rb") as f:
                chunks = pickle.load(f)
            logger.info(f"✅ Loaded {len(chunks)} chunks from cache")
            return chunks
        except Exception as e:
            logger.error(f"❌ Failed to load chunks from cache: {str(e)}")
    return None

def load_and_save_chunks(chunk_size=None, chunk_overlap=None):
    if not os.path.exists(DATA_PATH):
        logger.error(f"❌ DATA_PATH not found: {DATA_PATH}")
        return False

    try:
        docs = load_pdf_files() + load_epubs()
        if not docs:
            logger.warning("⚠️ No documents loaded")
            return False

        chunks = create_text_chunks(docs, chunk_size, chunk_overlap)
        if not chunks:
            logger.error("❌ No text chunks created")
            return False

        success = save_chunks_to_cache(chunks)
        del docs
        gc.collect()
        return success
    except Exception as e:
        logger.error(f"❌ Document processing failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    logger.info("🚀 Starting document processing...")
    success = load_and_save_chunks(chunk_size=2000, chunk_overlap=200)
    if success:
        logger.info("✨ Document processing completed successfully!")
    else:
        logger.warning("⚠️ Document processing completed with partial results")
