# API Key Setup for LLM Terms CDM Pipeline

This document explains how to configure API keys for the various services used by the LLM Terms CDM Entity Extraction Pipeline.

## Required API Keys

### 1. BioPortal API Key

**Purpose:** Required for BioPortal ontology search and mapping.

**How to Get:**
1. Go to [BioPortal](https://bioportal.bioontology.org/accounts)
2. Create an account or sign in
3. Generate an API key from your account settings

**Environment Variable:** `BIOPORTAL_API_KEY`

**Example:**
```bash
BIOPORTAL_API_KEY=your_actual_bioportal_api_key_here
```

### 2. Hugging Face Token

**Purpose:** Required for accessing certain biomedical models and datasets from Hugging Face.

**How to Get:**
1. Go to [Hugging Face Settings](https://huggingface.co/settings/tokens)
2. Create a new token (read access is usually sufficient)
3. Copy the token

**Environment Variable:** `HUGGINGFACE_TOKEN`

**Example:**
```bash
HUGGINGFACE_TOKEN=hf_your_actual_huggingface_token_here
```

## Optional API Keys

### 1. UMLS (Unified Medical Language System) API Key

**Purpose:** Optional - Only needed if using direct UMLS API calls instead of entity linker.

**Note:** This pipeline uses an entity linker approach, so the UMLS API key is **not required** for standard operation. Only configure this if you need direct UMLS API access for advanced features.

**How to Get:**
1. Go to [UMLS Registration](https://uts.nlm.nih.gov/uts/signup-login)
2. Create an account or sign in
3. Apply for UMLS access (requires research/academic justification)
4. Generate your API key from the profile section

**Environment Variable:** `UMLS_API_KEY`

**Example:**
```bash
UMLS_API_KEY=your_actual_umls_api_key_here
```

### 2. OpenAI API Key (Optional)

**Purpose:** If you prefer using OpenAI models instead of local Ollama models.

**How to Get:**
1. Go to [OpenAI Platform](https://platform.openai.com/api-keys)
2. Create an API key
3. Set up billing if required

**Environment Variable:** `OPENAI_API_KEY`

### 3. Anthropic API Key (Optional)

**Purpose:** If you prefer using Claude models for biomedical text processing.

**How to Get:**
1. Go to [Anthropic Console](https://console.anthropic.com/)
2. Create an API key
3. Set up billing if required

**Environment Variable:** `ANTHROPIC_API_KEY`

### 4. Google API Key (Optional)

**Purpose:** For Google models or services integration.

**How to Get:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create an API key
3. Set up billing if required

**Environment Variable:** `GOOGLE_API_KEY`

## Configuration Steps

### Option 1: Using the SLURM Script (Recommended)

The SLURM script automatically creates a `.env` file with placeholders. To configure:

1. **Run the SLURM script once** to generate the `.env` file:
   ```bash
   sbatch run_llm_terms_pipeline.sh
   ```

2. **Edit the generated `.env` file:**
   ```bash
   nano .env
   ```

3. **Replace placeholder values** with your actual API keys:
   ```bash
   # Before
   UMLS_API_KEY=your_umls_api_key_here

   # After
   UMLS_API_KEY=abcd1234-5678-efgh-ijkl-9012mnop3456
   ```

### Option 2: Manual Setup

1. **Create the `.env` file:**
   ```bash
   cat > .env << 'EOF'
   UMLS_API_KEY=your_umls_api_key_here
   BIOPORTAL_API_KEY=your_bioportal_api_key_here
   HUGGINGFACE_TOKEN=your_huggingface_token_here
   EOF
   ```

2. **Load the environment variables:**
   ```bash
   source .env
   ```

## Verification

The SLURM script automatically validates API keys and provides feedback:

```bash
=== VALIDATING API KEYS ===
✅ All API keys appear to be configured
```

Or info for optional keys:

```bash
ℹ️  Info: UMLS API key not configured
   - Using entity linker approach instead
   - UMLS API key only needed for direct API calls
```

## Pipeline Behavior with/without API Keys

| Feature | API Key Required | Behavior Without Key |
|---------|------------------|---------------------|
| Entity Linker UMLS Mapping | ❌ None (built-in) | Works normally using entity linker approach |
| Direct UMLS API Calls | ✅ UMLS_API_KEY | Skipped (optional advanced feature) |
| BioPortal Search | ✅ BIOPORTAL_API_KEY | Skipped, no ontology search results |
| Hugging Face Models | ✅ HUGGINGFACE_TOKEN | Uses only locally available models |
| Comprehensive Mapping | ✅ Any mapping key | Limited to available mapping services |
| Basic Entity Extraction | ❌ None | Works normally (core functionality) |

### Important Notes:
- **UMLS integration works via entity linker** - no API key needed for standard operation
- **UMLS API key is optional** - only needed for direct API calls (advanced features)
- **Entity extraction works fully** without any API keys using local models

## Security Notes

1. **Never commit API keys to version control**
2. **Use read-only permissions when possible**
3. **Rotate keys regularly**
4. **Monitor API usage for unusual activity**

## Troubleshooting

### Common Issues

1. **Invalid API Key Format**
   - Ensure no extra spaces or quotes
   - Check for special characters that need escaping

2. **API Key Not Working**
   - Verify the key is active and not expired
   - Check if you have sufficient permissions/quotas

3. **Network Issues**
   - Ensure cluster has internet access
   - Check firewall settings for API endpoints

### Debug Mode

Enable verbose logging to see API key usage:

```bash
python main.py --verbose --input-file your_file.txt
```

### Testing API Keys

Test individual API keys:

```bash
# Test UMLS API key
curl -H "Authorization: Bearer $UMLS_API_KEY" \
     "https://uts-ws.nlm.nih.gov/rest/content/current/CUI/C0006826"

# Test Hugging Face token
curl -H "Authorization: Bearer $HUGGINGFACE_TOKEN" \
     "https://huggingface.co/api/models"
```

## Support

For issues with specific API keys:
- **UMLS:** https://uts.nlm.nih.gov/uts/help
- **BioPortal:** https://bioportal.bioontology.org/help
- **Hugging Face:** https://huggingface.co/docs/hub/security-tokens