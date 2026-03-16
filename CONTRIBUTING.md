# Contributing to FormulaForge

Thank you for your interest in contributing to FormulaForge! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- AWS Account with Bedrock access enabled
- Git

### Local Development

```bash
# Clone the repository
git clone https://github.com/SMXFREEZE/formula-forge-hackathon.git
cd formula-forge-hackathon

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
npm ci

# Set environment variables
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
export AWS_REGION="us-east-1"

# Run the development server
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

## Project Structure

| File | Purpose | Lines |
|------|---------|-------|
| `formula_forge.py` | Core AI engine — NovaClient, FormulaSolver, full pipeline | ~2,000 |
| `app.py` | FastAPI backend — 20+ REST/WebSocket endpoints | ~1,400 |
| `index.html` | Full single-page frontend — glassmorphism UI | ~6,000 |
| `generate_slides.js` | Node.js PPTX pitch deck generator | ~1,500 |

## Code Style

- **Python**: Follow PEP 8. Use type hints for all function signatures.
- **JavaScript**: Use `const`/`let` (no `var`). Prefer async/await over callbacks.
- **Commit Messages**: Use conventional format: `feat:`, `fix:`, `docs:`, `refactor:`.

## Submitting Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Make your changes and test locally
4. Commit with a descriptive message
5. Push and open a Pull Request

## Reporting Issues

Please open a GitHub Issue with:
- Steps to reproduce
- Expected vs actual behavior
- Browser/OS/Python version
- Relevant error logs
