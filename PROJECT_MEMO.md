# SPIA — Project Memo
## Vision, Architecture, Current Status and Roadmap

**Project:** SPIA  
**Coordinator and creator:** Quickstar  
**Development model:** Human-led, multi-AI collaboration  
**Current stage:** Functional foundation / initial local Git baseline  
**Primary environment:** Linux / WSL Ubuntu  
**Default local service port:** 8767

---

## 1. Project vision

SPIA is intended to be a modular environment for organizing, managing, and developing multiple independent projects.

Its purpose is to provide a common workspace where a human coordinator can manage project files, code, documentation, configurations, and optional AI collaborators without losing the independence of each project.

SPIA is not intended to be tied to one AI provider, one model, one hardware platform, or one specific type of project.

The platform should remain useful even when no AI assistant is configured.

The guiding principle is:

**SPIA manages and organizes. AI assistants interpret, analyze, and suggest. The human coordinator authorizes important decisions.**

## 2. Core principles

1. **Human authority:** The user retains control over project decisions and actions.
2. **Modularity:** Features should be independent whenever practical.
3. **Provider independence:** Support different AI providers and models through interchangeable integrations.
4. **Optional AI:** SPIA must operate without an API key or AI assistant.
5. **Project isolation:** Each project has its own files, documentation, configuration, memory, and optional AI group.
6. **Traceability:** Decisions, discussions, and approved documentation should retain their origins.
7. **Resource awareness:** Prefer efficient solutions that work on modest hardware.
8. **Incremental development:** Build the foundation, use it in real projects, and improve it based on actual needs.

## 3. Main architecture

### 3.1 SPIA core

The core is responsible for:
- Starting and managing the local application.
- Providing the web interface and integrated terminal.
- Browsing and managing project files.
- Identifying project roots.
- Managing project configuration.
- Providing common services to optional modules.

The core must not depend on Puppy or on any external AI service.

### 3.2 Projects

Each project will have an independent directory and a `project.json` file containing:
- Unique project ID.
- Project name.
- Project-specific configuration.
- Optional integrations and AI group settings.

The `projects/` directory is the default discovery root.

New directories must not be silently registered as projects. SPIA should ask the user before registering them.

If a registered project is moved outside the discovery directory, SPIA should preserve its registration and offer a way to locate it again.

Each project may have its own:
- Documentation.
- Configuration.
- Memory.
- Files and source code.
- Optional AI collaboration group.

No automatic sharing of project memory between unrelated projects.

### 3.3 Silicon Puppy (SP)

Puppy is SPIA's optional general-purpose assistant.

Its responsibilities may include:
- Helping the user understand the platform.
- Interpreting project context when authorized.
- Suggesting actions and improvements.
- Helping organize information.
- Supporting project workflows.

Puppy's general memory must remain separate from project-specific memory.

Puppy must be honest about its actual capabilities and must never claim access to files, services, or systems that have not been integrated.

Puppy should remain independent of NVIDIA as a provider. The current NVIDIA integration is an initial implementation, not a permanent architectural restriction.

### 3.4 AI collaboration groups

Each project may have its own optional AI group.

Groups:
- Begin disabled.
- Are activated by the user.
- Include Puppy as a permanent member when the group is enabled.
- May include different AI providers and models.
- Must preserve the full conversation history according to configurable retention settings.

Group discussions are not automatically official project documentation.

A discussion may be converted into documentation only after review and approval. The resulting document should preserve its origin and distinguish hypotheses, suggestions, and confirmed results.

Not every project needs an AI group.

## 4. Current implementation

The current baseline contains:

- FastAPI backend in `server.py`.
- Main interface in `terminal.html`.
- Interface styling in `spia.css`.
- Integrated terminal and code editor interface.
- Editor bundle in `vendor/spia-editor.bundle.js`.
- Launcher script `spia`, with start, status, stop, and log commands.
- Python dependencies documented in `requirements.txt`.
- Silicon Puppy module directory `SP/`.
- Default project workspace directory `projects/`.
- Local Puppy chat integration using an NVIDIA API endpoint.
- Environment-based API key loading, keeping credentials outside the frontend and Git repository.

The local SPIA service uses port 8767.

The Puppy chat endpoint has been tested successfully. The API key is stored locally in `.env`, which is excluded from Git.

The editor bundle is included because it is required by the current interface.

### Current limitations

- Puppy library context is not yet implemented; its library endpoint currently returns HTTP 503.
- The project memory system is not yet implemented.
- AI groups are not yet implemented.
- Project registration and full project lifecycle management remain future work.
- Provider integrations beyond the current NVIDIA implementation remain future work.

The current version is therefore a functional foundation, not the completed SPIA vision.

## 5. Planned development

### Phase 1 — Foundation and stability

- [x] Establish the FastAPI backend.
- [x] Establish the main web interface.
- [x] Integrate the terminal and code editor.
- [x] Create the launcher and basic service management.
- [x] Implement the initial Puppy chat integration.
- [x] Separate API credentials from versioned source code.
- [x] Initialize the local Git repository.
- [ ] Register and document the initial baseline.
- [ ] Share the repository with the AI collaborators for review.

### Phase 2 — Project management

- [ ] Define and implement `project.json`.
- [ ] Implement explicit project registration.
- [ ] Implement project discovery and relocation.
- [ ] Create project-specific configuration management.
- [ ] Implement safe file and directory operations.
- [ ] Define project documentation organization.

### Phase 3 — Puppy

- [ ] Define Puppy's identity and permanent instructions.
- [ ] Implement general memory.
- [ ] Implement project-context access with clear permissions.
- [ ] Implement the knowledge library.
- [ ] Improve provider abstraction.
- [ ] Support changing providers without redesigning the SPIA core.

### Phase 4 — AI collaboration groups

- [ ] Implement optional project groups.
- [ ] Implement member and provider configuration.
- [ ] Implement group conversations.
- [ ] Preserve conversation history with configurable retention.
- [ ] Implement review and approval workflows.
- [ ] Convert approved discussions into traceable project documentation.

### Phase 5 — Integrated workspace

- [ ] Improve the unified workspace experience.
- [ ] Implement expandable and resizable panels.
- [ ] Adapt the interface to different project types.
- [ ] Improve project navigation and contextual tools.
- [ ] Refine usability based on real project workflows.

## 6. Git and repository policy

The SPIA repository contains the SPIA platform itself.

Project workspaces and their contents are excluded from the SPIA repository by default.

Local secrets, virtual environments, logs, temporary files, and backups must not be committed.

The `vendor/spia-editor.bundle.js` file remains versioned because the current application requires it.

The `include_in_git` setting should eventually be configurable per project rather than imposed globally.

The initial Git repository is local. No remote repository or public release should be created without explicit authorization from Quickstar.

## 7. Collaboration workflow

The AI collaborators should work from a shared understanding of the project.

When reviewing SPIA, each member should:
1. Read this memo.
2. Inspect the current repository state.
3. Distinguish implemented features from planned features.
4. Identify problems and opportunities without assuming unimplemented capabilities exist.
5. Submit suggestions for discussion.
6. Avoid changing files or making commits without authorization.

Technical proposals should include their rationale, consequences, and resource requirements.

The project coordinator decides which proposals become part of the official roadmap.

## 8. Current milestone

The immediate objective is to establish a clean, documented, functional baseline and share it with the collaborators.

The next development stage should be guided by:
- Their independent reviews.
- Actual use of SPIA.
- The problems encountered during real workflows.
- The available hardware and development resources.

We should avoid implementing every planned feature at once.

**Build the foundation. Use it. Learn from it. Improve it together.**

---

*This memo is a living project document. It should be updated when significant architectural decisions are approved or implementation milestones are completed.*
