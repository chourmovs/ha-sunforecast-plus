import os

OUTPUT_FILE = "combined_output.txt"
IGNORED_DIRS = {".git", ".github", "__pycache__", "venv", "node_modules", "translations"}
IGNORED_CONTENT_EXTENSIONS = {".md"}  # <--- Exclure ces fichiers du contenu détaillé
IGNORED_BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".exe", ".zip", ".tar", ".gz", ".7z"}

def should_ignore_dir(path):
    for ignored in IGNORED_DIRS:
        if f"/{ignored}/" in path.replace("\\", "/"):
            return True
    return False

def build_filetree():
    tree_lines = []
    for root, dirs, files in os.walk("."):
        if should_ignore_dir(root):
            continue
        indent = "  " * (root.count(os.sep))
        rel_root = os.path.relpath(root, ".")
        if rel_root != ".":
            tree_lines.append(f"{indent}- {rel_root}/")
        for file in sorted(files):
            full_path = os.path.join(root, file)
            if should_ignore_dir(full_path):
                continue
            tree_indent = "  " * (full_path.count(os.sep))
            tree_lines.append(f"{tree_indent}- {file}")
    return "\n".join(tree_lines)

def should_include_in_content(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in IGNORED_BINARY_EXTENSIONS:
        return False
    if ext in IGNORED_CONTENT_EXTENSIONS:
        return False
    return True

def main():
    content_parts = []

    # 1. Filetree en tête
    filetree = build_filetree()
    content_parts.append("# Arborescence du dépôt\n\n")
    content_parts.append(filetree)
    content_parts.append("\n\n---\n")

    # 2. Contenu détaillé
    for root, dirs, files in os.walk("."):
        for file in sorted(files):
            full_path = os.path.join(root, file)
            if full_path.startswith("./" + OUTPUT_FILE):
                continue
            if should_ignore_dir(full_path):
                continue
            if not should_include_in_content(full_path):
                continue
            relative_path = os.path.relpath(full_path, ".")
            content_parts.append(f"\n\n---\n# {relative_path}\n---\n\n")
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    content_parts.append(content)
            except Exception as e:
                content_parts.append(f"[Erreur de lecture: {e}]\n")

    combined_text = ''.join(content_parts)

    # 3. Estimation du nombre de tokens
    estimated_tokens = int(len(combined_text) / 4)
    combined_text += f"\n\n---\n# Estimation du nombre de tokens : {estimated_tokens} tokens\n"

    # 4. Sauvegarde
    with open(OUTPUT_FILE, "w", encoding="utf-8") as output:
        output.write(combined_text)

if __name__ == "__main__":
    main()
