import os

file_path = 'standalone_pipeline.py'

# Read as binary
with open(file_path, 'rb') as f:
    content = f.read()

# Try to decode as utf-8, ignoring errors to get the main part
try:
    text = content.decode('utf-8')
except UnicodeDecodeError:
    # If it fails, it might be because of the appended part.
    # The original file was UTF-8. The appended part might be UTF-16.
    # Let's try to find where the original ends.
    # We know the original ended with "if __name__ == '__main__':" block usually, 
    # but I appended to the end.
    # Let's try decoding with 'utf-8' and 'replace' to see what we have.
    text = content.decode('utf-8', errors='replace')

# Remove the appended garbage (the SemanticDeduplicator class at the end)
# The appended part likely starts after the last valid line of the original file.
# I'll look for the last "if __name__" block or similar.
# Or I can just search for "class SemanticDeduplicator" and remove it if it's at the end.

# Split into lines
lines = text.splitlines()

# Find where SemanticDeduplicator is appended (likely at the end)
# And remove it.
cleaned_lines = []
found_appended = False
for line in lines:
    if "class SemanticDeduplicator:" in line:
        # If this is the appended one (at the end), stop or skip
        # But I also want to insert it in the middle.
        # Let's just strip everything after the main execution block if possible.
        pass
    cleaned_lines.append(line)

# Actually, let's just read the file, find the appended part (which might be garbage chars if encoding is wrong),
# and cut it off.
# The original file ended with `main()` call?
# Let's look for `if __name__ == "__main__":`
main_block_idx = -1
for i, line in enumerate(lines):
    if 'if __name__ == "__main__":' in line or "if __name__ == '__main__':" in line:
        main_block_idx = i

# If we found the main block, the file should end shortly after.
# The `run_standalone_pipeline.sh` or similar might be at the end? No, it's python.
# The file ends with `sys.exit(0 if success else 1)` usually.

# Let's just truncate after the main block's execution.
# But I need to be careful not to delete valid code.

# Better approach:
# 1. Read the file.
# 2. Identify the "garbage" at the end (likely null bytes or replacement chars).
# 3. Remove them.
# 4. Insert SemanticDeduplicator before CDMEntityPipeline.

# Let's try to find "class CDMEntityPipeline"
pipeline_idx = -1
for i, line in enumerate(lines):
    if "class CDMEntityPipeline" in line:
        pipeline_idx = i
        break

semantic_deduplicator_code = """
class SemanticDeduplicator:
    \"\"\"Deduplicates entities using semantic similarity.\"\"\"

    def __init__(self, model_name: str = 'all-MiniLM-L6-v2', threshold: float = 0.85):
        self.threshold = threshold
        self.model = None
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(model_name)
            logger.info(f"🧠 Semantic deduplicator initialized with {model_name}")
        except ImportError:
            logger.warning("⚠️  sentence-transformers not installed. Semantic deduplication disabled.")
        except Exception as e:
            logger.warning(f"⚠️  Failed to load semantic model: {e}")

    def apply_semantic_deduplication(self, entities: List[Dict]) -> List[Dict]:
        \"\"\"Deduplicate entities based on semantic similarity.\"\"\"
        if not entities:
            return []
            
        if not self.model:
            # Fallback to exact string deduplication
            return self._exact_deduplication(entities)

        # First, exact deduplication to reduce work
        unique_entities = self._exact_deduplication(entities)
        if len(unique_entities) < 2:
            return unique_entities

        # Get embeddings
        terms = [e['entity'] for e in unique_entities]
        embeddings = self.model.encode(terms)

        # Compute similarity matrix
        from sklearn.metrics.pairwise import cosine_similarity
        similarity_matrix = cosine_similarity(embeddings)

        # Group similar entities
        # We use a simple greedy approach: take the first, find all similar, merge, repeat
        final_entities = []
        processed_indices = set()

        for i in range(len(unique_entities)):
            if i in processed_indices:
                continue

            current_group = [unique_entities[i]]
            processed_indices.add(i)

            for j in range(i + 1, len(unique_entities)):
                if j in processed_indices:
                    continue

                if similarity_matrix[i][j] >= self.threshold:
                    # Check if types match (optional, but safer)
                    if unique_entities[i]['entity_type'] == unique_entities[j]['entity_type']:
                        current_group.append(unique_entities[j])
                        processed_indices.add(j)

            # Merge group
            merged_entity = self._merge_entity_group(current_group)
            final_entities.append(merged_entity)

        return final_entities

    def _exact_deduplication(self, entities: List[Dict]) -> List[Dict]:
        \"\"\"Deduplicate by exact string match (case-insensitive).\"\"\"
        grouped = defaultdict(list)
        for e in entities:
            key = (e['entity'].lower().strip(), e['entity_type'])
            grouped[key].append(e)
        
        return [self._merge_entity_group(group) for group in grouped.values()]

    def _merge_entity_group(self, group: List[Dict]) -> Dict:
        \"\"\"Merge a group of duplicate entities into one.\"\"\"
        if not group:
            return {}
            
        # Pick the most frequent or longest form as the canonical name
        # For now, just pick the one with highest confidence or first
        best_entity = max(group, key=lambda x: x.get('confidence', 0))
        
        # Aggregate stats
        total_confidence = sum(e.get('confidence', 0) for e in group)
        avg_confidence = total_confidence / len(group)
        max_confidence = max(e.get('confidence', 0) for e in group)
        
        # Create merged object
        merged = best_entity.copy()
        merged['confidence'] = avg_confidence
        merged['avg_confidence_score'] = avg_confidence
        merged['max_confidence_score'] = max_confidence
        merged['frequency'] = len(group)
        merged['source_count'] = len(group)
        
        return merged
"""

# Insert the class
if pipeline_idx != -1:
    lines.insert(pipeline_idx, semantic_deduplicator_code)
else:
    print("Could not find CDMEntityPipeline class!")

# Remove the appended garbage at the end
# I'll look for the LAST "if __name__" and keep everything up to the end of that block.
# Assuming the file ends with the main block.
# I will just strip any lines that look like "class SemanticDeduplicator" appearing AFTER the insertion point.
# Or better, just write the file back and trust that I didn't duplicate it badly.
# But I know I appended it, so it's at the end.
# I'll truncate the file at the line where the appended content starts.
# The appended content starts with "class SemanticDeduplicator:".
# I inserted it at `pipeline_idx`. Any *other* occurrence should be removed.

final_lines = []
inserted = False
for i, line in enumerate(lines):
    if "class SemanticDeduplicator:" in line and i > pipeline_idx + 10: # +10 to avoid matching the one I just inserted
        # This is likely the appended one. Stop here?
        # Or just skip it and the following lines?
        # The appended part is at the very end.
        break
    final_lines.append(line)

# Write back as UTF-8
with open(file_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(final_lines))

print("File fixed successfully.")
