# Agent Python Tools

- repo: oats
- repo_uri: https://github.com/district-solutions/open-agent-tools-coder.git

## File: oats/hook/engine.py

Prompts

```
['build a HookEngine instance with a list of hook configuration dicts from coder.json', 'fire pre_tool_use hooks by calling engine.fire with a HookEvent and HookContext', 'create a HookContext with session_id, event, tool_name, and tool_args for hook execution', 'create a blocking HookResult with HookResult.block_result to stop tool execution with a message', 'parse a HookResult from a JSON dict returned by a hook command on stdout']
```

Usage

```
{'build_hook_engine': 'build a HookEngine instance with a list of hook configuration dicts from coder.json', 'fire_hook_event': 'fire pre_tool_use hooks by calling engine.fire with a HookEvent and HookContext', 'create_hook_context': 'create a HookContext with session_id, event, tool_name, and tool_args for hook execution', 'create_hook_result_block': 'create a blocking HookResult with HookResult.block_result to stop tool execution with a message', 'parse_hook_result_from_dict': 'parse a HookResult from a JSON dict returned by a hook command on stdout'}
```

