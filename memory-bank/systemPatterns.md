# System Patterns: y-cli

## Architecture Overview

### Core Components
```mermaid
flowchart TD
    CLI[CLI Layer] --> Commands[Command Modules]
    Commands --> Services[Service Layer]
    Services --> Repositories[Repository Layer]
    Services --> Providers[Provider Layer]
    
    subgraph "Data Flow"
        Repositories --> Storage[Storage]
        Providers --> External[External Services]
    end
```

## Design Patterns

### Repository Pattern
- Used for data persistence and retrieval
- Implemented in bot.repository, chat.repository, mcp_server.repository
- Abstracts storage operations from business logic
- Enables multiple storage backend implementations
- Concrete implementations for file and Cloudflare storage
- Organized in dedicated repository module for better structure

### Factory Pattern
- Implemented as repository/factory.py for chat storage
- Selects appropriate repository implementation based on configuration
- Enables runtime storage selection
- Provides clean abstraction for storage implementation details

### Service Layer Pattern
- Business logic encapsulation
- Service classes in bot.service, chat.service, mcp_server.service
- Coordinates between repositories and providers
- Handles complex operations and validations
- Async methods for improved performance

### Provider Pattern
- Abstracts external service interactions
- Base provider with common interface
- Specific implementations for different chat services
- Enables easy addition of new providers

### Command Pattern
- CLI commands as separate modules
- Consistent command structure
- Reusable command components
- Clear separation of concerns

## Component Relationships

### Chat System
```mermaid
flowchart LR
    ChatCmd[Chat Command] --> ChatSvc[Chat Service]
    ChatSvc --> RepoModule[Repository Module]
    ChatSvc --> ChatProv[Chat Providers]
    
    subgraph "Repository Module"
        RepoModule --> RepoFactory[Factory]
        RepoFactory --> FileRepo[File Repository]
        RepoFactory --> CloudRepo[Cloudflare Repository]
    end
    
    subgraph "Providers"
        ChatProv --> OpenAI[OpenAI Format]
        ChatProv --> Dify[Dify]
        ChatProv --> Topia[Topia]
    end
```

### Bot System
```mermaid
flowchart LR
    BotCmd[Bot Commands] --> BotSvc[Bot Service]
    BotSvc --> BotRepo[Bot Repository]
    BotSvc --> BotModel[Bot Models]
```

### MCP System
```mermaid
flowchart LR
    MCPCmd[MCP Commands] --> MCPSvc[MCP Service]
    MCPSvc --> MCPRepo[MCP Repository]
    MCPSvc --> MCPSys[MCP System]
```

## Key Technical Decisions

### Command Structure
- Modular command organization
- Consistent command patterns
- Reusable command components
- Clear help documentation

### Data Storage
- Abstract repository interface
- Multiple storage implementations:
  - File-based storage for simplicity
  - Cloudflare KV/R2 for cloud persistence
- JSON format for data serialization
- Repository factory for implementation selection
- Async operations for better performance

### Provider Integration
- Common provider interface
- Provider-specific implementations
- Consistent error handling
- Flexible configuration
- Async communication patterns

### MCP Implementation
- Standard protocol adherence
- Tool and resource abstraction
- Server management utilities
- System integration patterns

## Error Handling
- Consistent error patterns
- Clear error messages
- Error recovery strategies
- Logging and debugging support

## Extension Points
- New chat providers
- Additional bot features
- MCP server types
- Command modules
- Storage backends (implemented with Cloudflare)
- Additional cloud storage providers

## Testing Strategy
- Unit tests for core logic
- Integration tests for providers
- Command testing utilities
- Mock implementations
