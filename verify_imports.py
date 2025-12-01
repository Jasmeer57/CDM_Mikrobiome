import os
import ast
import sys
import importlib

def get_imports_from_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except Exception as e:
            print(f"Error parsing {filepath}: {e}")
            return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split('.')[0])
    return imports

def main():
    root_dir = r'C:\Users\jas\Desktop\Microbiome-CDM\llm_terms'
    all_imports = set()
    
    print(f"Scanning {root_dir} for Python files...")
    for subdir, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(subdir, file)
                file_imports = get_imports_from_file(filepath)
                all_imports.update(file_imports)

    print(f"Found {len(all_imports)} unique top-level imports.")
    
    # Filter out local modules (assuming they start with lowercase or are in the directory)
    # This is a heuristic. Better is to try importing.
    
    missing_modules = []
    installed_modules = []
    
    print("\nVerifying imports...")
    for module in sorted(all_imports):
        try:
            importlib.import_module(module)
            installed_modules.append(module)
            # print(f"[OK] {module}")
        except ImportError:
            # Check if it's a local module
            # Simple check: is there a folder or .py file with this name in llm_terms?
            is_local = False
            if os.path.exists(os.path.join(root_dir, module)) or \
               os.path.exists(os.path.join(root_dir, module + '.py')):
                is_local = True
            
            if not is_local:
                missing_modules.append(module)
                print(f"[MISSING] {module}")
            else:
                # print(f"[LOCAL] {module}")
                pass

    print("\n" + "="*30)
    print("Verification Summary")
    print("="*30)
    if missing_modules:
        print(f"FAILED. The following modules seem to be missing or failed to import:")
        for m in missing_modules:
            print(f" - {m}")
    else:
        print("SUCCESS. All non-local imports were successfully imported.")

if __name__ == "__main__":
    main()
