# Agent Python Tools

- repo: oats
- repo_uri: https://github.com/district-solutions/open-agent-tools-coder.git

## File: oats/cli/approval.py

Prompts

```
['create an ApprovalManager instance in AUTO mode to auto-approve all tool operations', 'check if a tool operation needs user approval using the ApprovalManager needs_approval method', 'prompt the user to approve a tool operation with yes, yes-all, no, or no-with-instructions options', 'set the approval mode to SUPERVISED to ask before each write or bash operation', 'auto-approve a specific tool type for the current session using the ApprovalManager', 'run the check_providers function to list all available providers and their configuration status', 'run the check_providers CLI module to display provider names, IDs, and whether each is configured', 'review the check_providers function that iterates over providers and prints their configuration status', 'summarize the check_providers function which uses rich.console to print provider configuration details', 'test the check_providers function to verify it correctly lists providers and handles misconfigured CODER_CONFIG_FILE']
```

Usage

```
{'create_approval_manager': 'create an ApprovalManager instance in AUTO mode to auto-approve all tool operations', 'check_needs_approval': 'check if a tool operation needs user approval using the ApprovalManager needs_approval method', 'prompt_approval': 'prompt the user to approve a tool operation with yes, yes-all, no, or no-with-instructions options', 'set_approval_mode': 'set the approval mode to SUPERVISED to ask before each write or bash operation', 'auto_approve_tool': 'auto-approve a specific tool type for the current session using the ApprovalManager'}
```

## File: oats/cli/check_providers.py

Prompts

```
['create an ApprovalManager instance in AUTO mode to auto-approve all tool operations', 'check if a tool operation needs user approval using the ApprovalManager needs_approval method', 'prompt the user to approve a tool operation with yes, yes-all, no, or no-with-instructions options', 'set the approval mode to SUPERVISED to ask before each write or bash operation', 'auto-approve a specific tool type for the current session using the ApprovalManager', 'run the check_providers function to list all available providers and their configuration status', 'run the check_providers CLI module to display provider names, IDs, and whether each is configured', 'review the check_providers function that iterates over providers and prints their configuration status', 'summarize the check_providers function which uses rich.console to print provider configuration details', 'test the check_providers function to verify it correctly lists providers and handles misconfigured CODER_CONFIG_FILE']
```

Usage

```
{'run_check_providers': 'run the check_providers function to list all available providers and their configuration status', 'check_providers_cli': 'run the check_providers CLI module to display provider names, IDs, and whether each is configured', 'review_check_providers': 'review the check_providers function that iterates over providers and prints their configuration status', 'summarize_check_providers': 'summarize the check_providers function which uses rich.console to print provider configuration details', 'test_check_providers': 'test the check_providers function to verify it correctly lists providers and handles misconfigured CODER_CONFIG_FILE'}
```

