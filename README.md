# SPIA
### A Modular Platform for Organizing and Developing Projects

SPIA is a public, modular platform under development, designed to organize, manage, and support multiple independent projects through a unified workspace.

Its architecture is designed to support optional AI assistance, project isolation, and collaborative workflows involving multiple AI providers.

## Vision

SPIA aims to provide a unified environment where people can organize their projects, access their tools, maintain documentation, and collaborate with AI assistants without becoming dependent on a single provider or model.

**The human remains in control. AI assists; the user decides.**

## Core Principles

- **Modularity:** Components can evolve independently.
- **Project isolation:** Each project maintains its own context and documentation.
- **Provider independence:** AI integrations should support different providers and models.
- **Optional AI:** The platform must remain useful without an AI provider or API key.
- **Transparency:** Implemented features are distinguished from planned capabilities.
- **Human authority:** Important decisions and changes remain under user control.

## Current Implementation

The initial functional baseline includes:

- FastAPI-based backend.
- Integrated web terminal and workspace interface.
- Code editor integration.
- Project workspace discovery.
- Optional Silicon Puppy AI chat integration.
- Local configuration through environment variables.
- Git-based version control.

## Silicon Puppy

Silicon Puppy (SP) is the optional AI assistant associated with SPIA.

It is intended to provide general assistance and, in future stages, project-aware support and participation in collaborative AI groups.

The current baseline includes an NVIDIA NIM chat integration. Additional providers and capabilities are planned.

## Development Roadmap

| Area | Status |
|---|---|
| Core backend and interface | Implemented |
| Integrated code editor | Implemented |
| Basic Puppy chat | Implemented |
| Project lifecycle management | Planned |
| Project-specific memory | Planned |
| Multi-AI collaborative groups | Planned |
| Expanded provider support | Planned |

## Requirements

- Python 3.13 or compatible version
- Linux environment or WSL
- Dependencies listed in `requirements.txt`

## Getting Started

Clone the repository:

```bash
git clone https://github.com/Quickstarjr/SPIA.git
cd SPIA
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start SPIA:

```bash
./spia start
```

Check the local server status:

```bash
./spia status
```

The optional Puppy integration requires its provider API key to be configured locally. Never commit API keys or other secrets.

## Project Structure

```text
SPIA/
├── SP/          # Silicon Puppy documentation
├── projects/    # Default managed project workspace
├── vendor/      # Third-party editor assets
├── server.py    # Backend
├── terminal.html
├── spia.css
├── spia         # Launcher
└── requirements.txt
```

## Collaboration

SPIA is developed through human-led collaboration involving its creator and multiple AI assistants.

See [CONTRIBUTORS.md](CONTRIBUTORS.md) for contributor acknowledgments and [PROJECT_MEMO.md](PROJECT_MEMO.md) for the project's vision, architecture, current state, and roadmap.

## License

No license has been added yet. Until one is selected, the project should not be assumed to grant permissions beyond the rights provided by applicable copyright law.