import os
from app.config.config import DATA_PATH

def list_data_files():
    print(f"📂 DATA_PATH: {DATA_PATH}\n")
    if not os.path.exists(DATA_PATH):
        print("❌ DATA_PATH does not exist")
        return

    for root, dirs, files in os.walk(DATA_PATH):
        level = root.replace(DATA_PATH, "").count(os.sep)
        indent = " " * 4 * level
        print(f"{indent}{os.path.basename(root)}/")
        subindent = " " * 4 * (level + 1)
        for f in files:
            print(f"{subindent}{f}")

if __name__ == "__main__":
    list_data_files()
