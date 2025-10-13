import pickle

# Path to your file
path = "cache/chunks.pkl"

# Load the data
with open(path, "rb") as f:
    chunks = pickle.load(f)

# Check the type and size
print(f"Type: {type(chunks)}")
print(f"Number of items: {len(chunks)}")

# Inspect the first few entries
for i, chunk in enumerate(chunks[:3]):
    print(f"\n--- Chunk {i+1} ---")
    print(chunk if isinstance(chunk, str) else chunk.page_content)
