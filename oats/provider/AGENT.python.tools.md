# Agent Python Tools

- repo: oats
- repo_uri: https://github.com/district-solutions/open-agent-tools-coder.git

## File: oats/provider/models.py

Prompts

```
['create a Model dataclass instance with id, provider_id, name, context_length, and cost fields', 'get the LiteLLM model identifier string from a Model instance using the litellm_model property', 'register a new Model into the ModelRegistry using the register method with a Model instance', 'get a specific Model from the registry by provider_id and model_id using the get method', 'list all available models or filter by provider_id using the list_models function', 'get a configured AI provider by ID or use the default provider from config', 'send a completion request to an LLM provider with retry logic and exponential backoff', 'stream a completion from an LLM provider yielding chunks as they arrive', 'parse tool calls embedded in text content from open-source models like Qwen or Hermes', 'list all available AI providers registered in the provider registry']
```

Usage

```
{'create_Model': 'create a Model dataclass instance with id, provider_id, name, context_length, and cost fields', 'get_model_litellm_model': 'get the LiteLLM model identifier string from a Model instance using the litellm_model property', 'register_ModelRegistry': 'register a new Model into the ModelRegistry using the register method with a Model instance', 'get_model_registry_get': 'get a specific Model from the registry by provider_id and model_id using the get method', 'list_models': 'list all available models or filter by provider_id using the list_models function'}
```

## File: oats/provider/provider.py

Prompts

```
['create a Model dataclass instance with id, provider_id, name, context_length, and cost fields', 'get the LiteLLM model identifier string from a Model instance using the litellm_model property', 'register a new Model into the ModelRegistry using the register method with a Model instance', 'get a specific Model from the registry by provider_id and model_id using the get method', 'list all available models or filter by provider_id using the list_models function', 'get a configured AI provider by ID or use the default provider from config', 'send a completion request to an LLM provider with retry logic and exponential backoff', 'stream a completion from an LLM provider yielding chunks as they arrive', 'parse tool calls embedded in text content from open-source models like Qwen or Hermes', 'list all available AI providers registered in the provider registry']
```

Usage

```
{'get_provider': 'get a configured AI provider by ID or use the default provider from config', 'Provider_complete': 'send a completion request to an LLM provider with retry logic and exponential backoff', 'Provider_stream': 'stream a completion from an LLM provider yielding chunks as they arrive', 'parse_tool_calls_from_text': 'parse tool calls embedded in text content from open-source models like Qwen or Hermes', 'list_providers': 'list all available AI providers registered in the provider registry'}
```

