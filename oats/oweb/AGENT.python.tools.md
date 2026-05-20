# Agent Python Tools

- repo: oats
- repo_uri: https://github.com/district-solutions/open-agent-tools-coder.git

## File: oats/oweb/get_auth.py

Prompts

```
['get auth credentials as a tuple of url, email, and password from environment variables', 'get auth credentials by passing url, email, and password directly to get_auth_env', 'get auth credentials with verbose logging enabled to see auth type details', 'review the get_auth_env function to understand how it resolves url protocols and env variables', 'refactor get_auth_env to support additional environment variable names beyond CODER_CHAT_URL', 'login to the Open WebUI API with email and password to get an auth token', 'login to Open WebUI using CODER_CHAT_URL, CODER_CHAT_EMAIL, and CODER_CHAT_PASSWORD environment variables', 'login to Open WebUI by passing a custom base_url instead of relying on environment variables', 'login to Open WebUI with verbose logging enabled to see the signin request details', 'review the login_to_openwebui function error handling for bad request and network failures']
```

Usage

```
{'get_auth_credentials': 'get auth credentials as a tuple of url, email, and password from environment variables', 'get_auth_with_params': 'get auth credentials by passing url, email, and password directly to get_auth_env', 'get_auth_verbose': 'get auth credentials with verbose logging enabled to see auth type details', 'review_get_auth_env': 'review the get_auth_env function to understand how it resolves url protocols and env variables', 'refactor_get_auth_env': 'refactor get_auth_env to support additional environment variable names beyond CODER_CHAT_URL'}
```

## File: oats/oweb/login.py

Prompts

```
['get auth credentials as a tuple of url, email, and password from environment variables', 'get auth credentials by passing url, email, and password directly to get_auth_env', 'get auth credentials with verbose logging enabled to see auth type details', 'review the get_auth_env function to understand how it resolves url protocols and env variables', 'refactor get_auth_env to support additional environment variable names beyond CODER_CHAT_URL', 'login to the Open WebUI API with email and password to get an auth token', 'login to Open WebUI using CODER_CHAT_URL, CODER_CHAT_EMAIL, and CODER_CHAT_PASSWORD environment variables', 'login to Open WebUI by passing a custom base_url instead of relying on environment variables', 'login to Open WebUI with verbose logging enabled to see the signin request details', 'review the login_to_openwebui function error handling for bad request and network failures']
```

Usage

```
{'login_to_openwebui': 'login to the Open WebUI API with email and password to get an auth token', 'login_with_env_vars': 'login to Open WebUI using CODER_CHAT_URL, CODER_CHAT_EMAIL, and CODER_CHAT_PASSWORD environment variables', 'login_with_custom_url': 'login to Open WebUI by passing a custom base_url instead of relying on environment variables', 'login_verbose_mode': 'login to Open WebUI with verbose logging enabled to see the signin request details', 'review_login_error_handling': 'review the login_to_openwebui function error handling for bad request and network failures'}
```

