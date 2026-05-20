# Agent Python Tools

- repo: oats
- repo_uri: https://github.com/district-solutions/open-agent-tools-coder.git

## File: oats/plugins/loader.py

Prompts

```
['install all enabled plugins by calling install with an optional model_id filter', 'load all plugin manifests that pass activation gates and return the activated list', 'register a tool with the tool registry via PluginContext.register_tool from a plugin activate function', 'register a user-facing slash command handler via PluginContext.register_slash_command for the interactive REPL', 'get a read-only snapshot of all registered slash commands via get_slash_commands', 'discover all plugin manifests from default or custom root directories', 'validate a plugin manifest JSON file and return a PluginManifest model', 'check if a PluginManifest matches a given model id using matches_model', 'create a PluginProvides model declaring toolsets, tools, hooks, and slash commands', 'get the default plugin discovery root paths for user, project, and builtin plugins']
```

Usage

```
{'install_plugins': 'install all enabled plugins by calling install with an optional model_id filter', 'load_all_plugins': 'load all plugin manifests that pass activation gates and return the activated list', 'register_tool': 'register a tool with the tool registry via PluginContext.register_tool from a plugin activate function', 'register_slash_command': 'register a user-facing slash command handler via PluginContext.register_slash_command for the interactive REPL', 'get_slash_commands': 'get a read-only snapshot of all registered slash commands via get_slash_commands'}
```

## File: oats/plugins/manifest.py

Prompts

```
['install all enabled plugins by calling install with an optional model_id filter', 'load all plugin manifests that pass activation gates and return the activated list', 'register a tool with the tool registry via PluginContext.register_tool from a plugin activate function', 'register a user-facing slash command handler via PluginContext.register_slash_command for the interactive REPL', 'get a read-only snapshot of all registered slash commands via get_slash_commands', 'discover all plugin manifests from default or custom root directories', 'validate a plugin manifest JSON file and return a PluginManifest model', 'check if a PluginManifest matches a given model id using matches_model', 'create a PluginProvides model declaring toolsets, tools, hooks, and slash commands', 'get the default plugin discovery root paths for user, project, and builtin plugins']
```

Usage

```
{'discover_plugin_manifests': 'discover all plugin manifests from default or custom root directories', 'validate_plugin_manifest': 'validate a plugin manifest JSON file and return a PluginManifest model', 'check_model_support': 'check if a PluginManifest matches a given model id using matches_model', 'create_plugin_provides': 'create a PluginProvides model declaring toolsets, tools, hooks, and slash commands', 'get_default_plugin_roots': 'get the default plugin discovery root paths for user, project, and builtin plugins'}
```

