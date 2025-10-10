from sentence_transformers import SentenceTransformer

# This will download and cache the model
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

print("Model downloaded and cached successfully.")
