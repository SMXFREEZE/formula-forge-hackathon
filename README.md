<p align="center">
  <h1 align="center">🧪 FormulaForge</h1>
  <p align="center">
    <strong>AI-Powered Cosmetic Formulation Optimization Agent</strong>
  </p>
  <p align="center">
    Built 100% on the <b>Amazon Web Services</b> ecosystem — Bedrock Nova · Polly · S3
  </p>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#tech-stack">Tech Stack</a> •
  <a href="#getting-started">Getting Started</a> •
  <a href="#api-reference">API Reference</a> •
  <a href="#deployment">Deployment</a> •
  <a href="#license">License</a>
</p>

---

## Overview

**FormulaForge** is a full-stack, agentic AI application that designs, optimizes, and evaluates custom cosmetic formulations end-to-end. It combines **Amazon Nova** large language models with a **PuLP linear-programming solver** to create scientifically optimized skincare products — then generates branding assets, regulatory reports, and even a live AI dermatologist video call.

> **Hackathon Project** — Built for the Amazon Nova Hackathon by [Sami](https://github.com/SMXFREEZE) (FormulaForge / OraxAI).

---

## Features

### 🔬 Agentic Formulation Pipeline
A multi-step, self-correcting agent loop that goes from a text prompt (or ingredient label scan) to a fully optimized formula:

| Step | Name | Description |
|------|------|-------------|
| 1 | **PARSE** | Nova Pro parses user input into structured ingredient JSON |
| 2 | **OPTIMIZE** | PuLP LP solver maximizes performance under cost & regulatory constraints |
| 3 | **EXPLAIN** | Nova writes a scientific explanation of the optimized formula |
| 4 | **EVALUATE** | Nova critiques the formula and proposes constraint refinements |
| 5 | **RE-OPTIMIZE** | Solver runs again with agent-suggested adjustments (true agent loop) |
| 6 | **COMPARE** | Side-by-side delta analysis of v1 vs v2 with improvement narrative |
| 7 | **BRAND** | Auto-generates brand identity: name, palette, tagline |
| 8 | **VISUALIZE** | Nova Canvas generates product mockup images |
| 9 | **VIDEO** | Nova Reel renders a turntable product video |
| 10 | **SLIDES** | Auto-generates a branded PowerPoint pitch deck |

### 📹 Live AI Video Call — "Dr. Veda"
A real-time WebSocket-powered video consultation with an AI dermatologist:
- **Webcam Vision**: Streams live video frames to Amazon Nova Lite for multimodal skin analysis
- **Structured Observations**: Returns JSON with per-zone observations (area, condition, severity, confidence)
- **Voice TTS**: Amazon Polly neural voice responds aloud with clinical feedback
- **Multi-Turn Context**: Maintains conversational history across the full session
- **Scan Phases**: Automatically progresses through positioning → active scan → clinical feedback

### 🧠 AI-Powered Endpoints
- **Skin Analysis** — Upload a selfie for comprehensive dermatological analysis with product recommendations
- **Ingredient Label Scanner** — Photograph a product label to extract and parse ingredients via Nova vision
- **Chat Assistant** — Conversational AI for formula Q&A with full context awareness
- **Campaign Studio** — Generate brand copy, social media captions, and marketing assets
- **Clinical & Patent Review** — Deep reasoning analysis of formula novelty and safety
- **Outreach Email Generator** — Professional buyer outreach emails for retail distribution
- **Competitor Teardown** — Upload a competitor product image for AI-powered reverse engineering
- **Product Name Generator** — Creates luxury product name options with taglines
- **Ingredient Substitution** — AI-powered alternative ingredient suggestions with rationale
- **Stability & Shelf-Life Predictor** — Formula stability risk analysis and shelf-life estimation
- **INCI Name Converter** — Convert common names to official INCI nomenclature
- **Multi-Market Regulatory Report** — Compliance check against EU, FDA, Health Canada, and ASEAN
- **Ingredient Deep Dive** — Detailed ingredient profile cards with mechanism of action
- **Product Search** — Find real products with prices based on skin concerns
- **Ingredient Safety Checker** — Regulatory safety alerts for ingredient combinations

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Frontend (index.html)              │
│  Vanilla HTML/CSS/JS · Glassmorphism UI · WebSocket  │
└───────────────┬─────────────────────┬───────────────┘
                │  REST/SSE           │  WebSocket
                ▼                     ▼
┌───────────────────────┐   ┌─────────────────────────┐
│   FastAPI Backend      │   │  Video Call Handler      │
│   (app.py)             │   │  WebSocket /api/s2s      │
│                        │   │                          │
│  • 20+ REST endpoints  │   │  • Live webcam frames    │
│  • SSE pipeline stream │   │  • Multi-turn chat       │
│  • Job queue system    │   │  • Polly TTS → browser   │
└───────────┬────────────┘   └──────────┬──────────────┘
            │                           │
            ▼                           ▼
┌─────────────────────────────────────────────────────┐
│              FormulaForge Engine                     │
│              (formula_forge.py)                      │
│                                                      │
│  NovaClient ──→ AWS Bedrock (Nova Pro / Lite)        │
│  FormulaSolver ──→ PuLP LP Optimizer                 │
│  Polly TTS ──→ Amazon Polly Neural                   │
│  Canvas ──→ Amazon Nova Canvas (image gen)           │
│  Reel ──→ Amazon Nova Reel (video gen)               │
│  Slides ──→ Node.js pptxgenjs                        │
└─────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────┐
│                 AWS Services                         │
│                                                      │
│  Amazon Bedrock    │  Amazon Polly   │  Amazon S3     │
│  (Nova Pro/Lite/   │  (Neural TTS)   │  (Reel video   │
│   Canvas/Reel)     │                 │   output)      │
└─────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **AI Models** | Amazon Nova Pro, Nova Lite, Nova Canvas, Nova Reel (via AWS Bedrock) |
| **Voice** | Amazon Polly (Neural TTS) with Web Speech API fallback |
| **Backend** | Python 3.10 · FastAPI · Uvicorn · WebSockets |
| **Optimization** | PuLP (Linear Programming solver) |
| **Frontend** | Vanilla HTML/CSS/JS · Glassmorphism design · CSS animations |
| **Slides** | Node.js · pptxgenjs |
| **Infrastructure** | Docker · Render (PaaS) |
| **Cloud** | AWS Bedrock · AWS Polly · AWS S3 |

---

## Getting Started

### Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **AWS Account** with Bedrock access enabled for Nova models
- **AWS Credentials** configured via environment variables or AWS CLI

### 1. Clone the Repository

```bash
git clone https://github.com/SMXFREEZE/formula-forge-hackathon.git
cd formula-forge-hackathon
```

### 2. Install Dependencies

```bash
# Python
pip install -r requirements.txt

# Node.js (for slide generation)
npm ci
```

### 3. Configure AWS Credentials

```bash
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"
```

Or use an AWS credentials profile:
```bash
aws configure
```

### 4. Run the Application

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## API Reference

### Core Pipeline

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/generate` | Start the full formulation pipeline (returns job_id for SSE) |
| `GET` | `/events/{job_id}` | SSE stream for real-time pipeline progress |
| `POST` | `/scan_image` | Scan ingredient label image via Nova vision |

### AI Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/analyze_skin` | Upload selfie for comprehensive skin analysis |
| `POST` | `/chat` | Conversational AI with formula context |
| `POST` | `/premier_analysis` | Clinical & patent deep reasoning review |
| `POST` | `/stability_analysis` | Formula stability risk & shelf-life prediction |
| `POST` | `/regulatory_report` | Multi-market regulatory compliance check |

### Formulation Tools

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/suggest_alternatives` | AI-powered ingredient substitution |
| `POST` | `/inci_convert` | Convert to official INCI nomenclature |
| `POST` | `/ingredient_deepdive` | Detailed ingredient profile card |
| `POST` | `/ingredient_safety` | Safety & regulatory alerts |
| `POST` | `/product_search` | Find real products by skin concern |

### Branding & Marketing

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/generate_names` | Luxury product name generator |
| `POST` | `/campaign` | Generate full marketing campaign assets |
| `POST` | `/outreach_email` | Professional buyer outreach email |
| `POST` | `/competitor_teardown` | Reverse-engineer competitor products |

### Real-Time

| Method | Endpoint | Description |
|--------|----------|-------------|
| `WebSocket` | `/api/s2s?mode=video_call` | Live AI dermatologist video call |
| `WebSocket` | `/api/s2s?mode=voice` | Voice chat assistant |

---

## Deployment

### Docker

```bash
docker build -t formula-forge .
docker run -p 8000:8000 \
  -e AWS_ACCESS_KEY_ID="..." \
  -e AWS_SECRET_ACCESS_KEY="..." \
  -e AWS_REGION="us-east-1" \
  formula-forge
```

### Render (One-Click)

This project includes a `render.yaml` blueprint for instant deployment:

1. Fork this repository
2. Connect your GitHub to [Render](https://render.com)
3. Create a **New Blueprint** and select this repo
4. Add your AWS credentials in the Render dashboard Environment tab
5. Deploy 🚀

---

## Project Structure

```
formula-forge-hackathon/
├── app.py                 # FastAPI backend (20+ endpoints, WebSocket, SSE)
├── formula_forge.py       # Core agentic engine (NovaClient, FormulaSolver, pipeline)
├── index.html             # Full frontend (single-page app, glassmorphism UI)
├── generate_slides.js     # Node.js PPTX pitch deck generator
├── Dockerfile             # Production Docker image
├── render.yaml            # Render PaaS deployment blueprint
├── requirements.txt       # Python dependencies
├── package.json           # Node.js dependencies
├── policy.json            # AWS S3 bucket policy for Nova Reel
└── README.md              # This file
```

---

## AWS IAM Permissions

The application requires the following AWS permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "polly:SynthesizeSpeech",
        "s3:PutObject",
        "s3:GetObject",
        "s3:GetBucketLocation"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Key Design Decisions

- **100% AWS-Powered**: Every AI call routes through Amazon Bedrock (Nova) and Amazon Polly — zero third-party AI dependencies
- **Agentic Loop**: The optimizer runs, gets critiqued by Nova, then re-optimizes — a true self-improving agent pattern
- **Constraint Auto-Repair**: The LP solver pre-checks for infeasible constraints and automatically relaxes them before solving
- **Regulatory Guardrails**: Built-in EU/FDA regulatory limits are enforced at the data model level
- **Graceful Degradation**: TTS falls back to Web Speech API when Polly permissions are unavailable; STT stub prevents infinite loops

---

## Author

**Sami** — [GitHub](https://github.com/SMXFREEZE)
FormulaForge / OraxAI

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
