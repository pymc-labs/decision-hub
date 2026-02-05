
## Tech Stack

- **Python 3.11+** with type hints
- **FastAPI** for REST API
- **Typer + Rich** for CLI
- **OpenAI** for  LLM 
- **Pydantic** for data validation and settings
- **boto3** for S3 access


**Important**: Always use `uv run` to execute Python code, not `python` directly.


## Coding Conventions

- Use **frozen dataclasses** for immutable data models
- Prefer **pure functions** over classes - use modules to group related functions
- Use comments to explain what the business logic and document assumptions and choices not to explain the code verbatim

## Design Principles

- **Single responsibility**: Small, single-purpose functions with one clear reason to change - **Clear interfaces**: Descriptive names, type hints, explicit signatures - 
obvious inputs, outputs, and behavior - **Domain/infrastructure separation**: Keep business logic independent from frameworks, I/O, databases. UI, persistence, and external 
services are replaceable adapters around a clean core - **Testing as design**: Design for fast, focused unit tests. Pure functions and small units guide architecture - 
**Readability over cleverness**: Straightforward, idiomatic Python over opaque tricks. Follow PEP 8 - **YAGNI**: No abstractions or features "just in case" - add complexity 
only for concrete needs - **Continuous refactoring**: Ship the simplest thing that works, refactor as requirements evolve. Routine maintenance, not heroic effort - **Don't 
worship backward compatibility**: Don't freeze bad designs to avoid breaking changes. Provide clear migration paths instead of stacking hacks - **DRY** do not repeat yourself 
refactor the code an ensure ## Data Flow


## Testing

- Use `pytest` with fixtures in `conftest.py`
- Mock external services (S3, OpenAI, Database) in tests
## Documentation

After implementing significant changes, always check if the README.md needs updating. Update it for:
- New CLI commands or changed command behavior
- New API endpoints or changed API behavior
- New features or capabilities
- Changes to setup/configuration requirements
- Architectural changes that affect how the system works

Do NOT document implementation details - only high-level features and usage.
