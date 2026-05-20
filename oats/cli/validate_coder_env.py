#!/usr/bin/env python3
"""Validate the CODER_CONFIG_FILE environment and provider/model configuration.

Checks that the ``CODER_CONFIG_FILE`` env var is set, points to a valid JSON
file, and contains the expected provider and model definitions. Raises
``Exception`` with a detailed error message on any validation failure.
"""
from oats.log import gl
log = gl('validate_coder_env')

def validate_coder_env(provider_id: str, model_id: str | None = None, verbose: bool = False) -> bool:
    """Validate the coder environment configuration for a given provider and model.

    Checks in order:
    1. ``CODER_CONFIG_FILE`` env var is set and non-empty.
    2. The file exists and contains valid JSON.
    3. The JSON has a ``provider`` root key with the requested ``provider_id``.
    4. The provider definition has a ``base_url`` and a ``models`` list.
    5. If ``model_id`` is given, it exists in the provider's models list.

    Args:
        provider_id: The provider ID to look up in the config.
        model_id: Optional model ID to validate against the provider's models.
        verbose: If True, log a success message.

    Returns:
        ``True`` if validation passes.

    Raises:
        Exception: With a detailed error message if any check fails.
    """
    import os
    import ujson as json
    from oats.pp import pp
    found_base_url = None
    config_dict = {}
    coder_config_file = os.getenv('CODER_CONFIG_FILE', None)
    if coder_config_file is None:
        err_msg = f'### Sorry!!💥 The environment variable: ``CODER_CONFIG_FILE`` is missing. Please create your own oats/coder.json file outside the repo and then export it with:\n```\nexport CODER_CONFIG_FILE=PATH/coder.json\n```\n'
        log.info(err_msg)
        raise Exception('Please fix the CODER_CONFIG_FILE for the logged error')
    else:
        config_contents = ''
        with open(coder_config_file, 'r') as file:
            config_contents = file.read()
        if config_contents == '':
            err_msg = f'### Sorry!!💥 The CODER_CONFIG_FILE is empty. Please check the environment variable: ``CODER_CONFIG_FILE`` file is at that path and is a valid coder.json file like the ``oats/config/coder.json``\n\nHere is the path to the current config:\n```\nexport CODER_CONFIG_FILE={coder_config_file}\n```\n'
            log.info(err_msg)
            raise Exception('Please fix the CODER_CONFIG_FILE for the logged error')
        try:
            config_dict = json.loads(config_contents)
        except Exception:
            err_msg = f'### Sorry!!💥 The CODER_CONFIG_FILE has ❗💥 ``invalid JSON``💥❗. Please check the environment variable: ``CODER_CONFIG_FILE`` file is at that path and is a valid coder.json file like the ``oats/config/coder.json``\n\nHere is the path to the current config:\n```\nexport CODER_CONFIG_FILE={coder_config_file}\n```\nCurrent CODER_CONFIG_FILE contents:\n```\n{config_contents}\n```\n'
            log.info(err_msg)
            raise Exception('Please fix the CODER_CONFIG_FILE for the logged error')
    if len(config_dict) == 0:
        err_msg = f'### Sorry!!💥 The CODER_CONFIG_FILE does not have any valid model providers. Please check the environment variable: ``CODER_CONFIG_FILE`` file is at that path and is a valid coder.json file like the ``oats/config/coder.json``\n\nHere is the ``coder.js  on`` config dictionary:\n```\n{pp(config_dict)}\n```\n\nHere is the path to the current config:\n```\nexport CODER_CONFIG_FILE={coder_config_file}\n```\n'
        log.info(err_msg)
        raise Exception('Please fix the CODER_CONFIG_FILE for the logged error')
    if 'provider' not in config_dict:
        err_msg = f'### Sorry!!💥 The CODER_CONFIG_FILE is missing the ``provider`` root key. Please check the environment variable: ``CODER_CONFIG_FILE`` file is at that path and is a valid coder.json file like the ``oats/config/coder.json``\n\nHere is the ``coder.js  on`` config dictionary:\n```\n{pp(config_dict)}\n```\n\nHere is the path to the current config:\n```\nexport CODER_CONFIG_FILE={coder_config_file}\n```\n'
        log.info(err_msg)
        raise Exception('Please fix the CODER_CONFIG_FILE for the logged error')
    if provider_id not in config_dict['provider']:
        err_msg = f'### Sorry!!💥 The CODER_CONFIG_FILE is missing the provider_id: ``{provider_id}`` in the providers root key dictionary. Please check the environment variable: ``CODER_CONFIG_FILE`` file is at that path and is a valid coder.json file like the ``oats/config/coder.json``\n\nHere is the ``coder.json`` config dictionary:\n```\n{pp(config_dict)}\n```\n\nHere is the path to the current config:\n```\nexport CODER_CONFIG_FILE={coder_config_file}\n```\n'
        log.info(err_msg)
        raise Exception('Please fix the CODER_CONFIG_FILE for the logged error')
    if 'models' not in config_dict['provider'][provider_id]:
        err_msg = f'### Sorry!!💥 The CODER_CONFIG_FILE is missing the ``models`` list in the provider_id: ``{provider_id}`` definition. Please check the environment variable: ``CODER_CONFIG_FILE`` file is at that path and is a valid coder.json file like the ``oats/config/coder.json``\n\nHere is the ``coder.json`` config dictionary:\n```\n{pp(config_dict)}\n```\n\nHere is the path to the current config:\n```\nexport CODER_CONFIG_FILE={coder_config_file}\n```\n'
        log.info(err_msg)
        raise Exception('Please fix the CODER_CONFIG_FILE for the logged error')
    found_model = False
    if 'base_url' not in config_dict['provider'][provider_id]:
        err_msg = f'### Sorry!!💥 The CODER_CONFIG_FILE is missing a ``base_url`` for the provider_id: ``{provider_id}`` to reach the backend ai service. Please check the environment variable: ``CODER_CONFIG_FILE`` file is at that path and is a valid coder.json file like the ``oats/config/coder.json``\n\nHere is the ``coder.json`` config dictionary:\n```\n{pp(config_dict)}\n```\n\nHere is the path to the current config:\n```\nexport CODER_CONFIG_FILE={coder_config_file}\n```\n'
        log.info(err_msg)
        raise Exception('Please fix the CODER_CONFIG_FILE for the logged error')
    if model_id is not None and model_id != '':
        for model_node in config_dict['provider'][provider_id]['models']:
            if 'name' not in model_node:
                err_msg = f'### Sorry!!💥 The CODER_CONFIG_FILE provider_id: ``{provider_id}`` is missing a valid model dictionary in the ``models`` list.\n\nPlease check the environment variable: ``CODER_CONFIG_FILE`` file is at that path and is a valid coder.json file like the ``oats/config/coder.json``\n\nHere is the ``coder.json`` config dictionary:\n```\n{pp(config_dict)}\n```\n\nHere is the path to the current config:\n```\nexport CODER_CONFIG_FILE={coder_config_file}\n```\n'
                log.info(err_msg)
                raise Exception('Please fix the CODER_CONFIG_FILE for the logged error')
            else:
                if model_id in model_node['name']:
                    found_model = True
                    break
        if not found_model:
            err_msg = f'### Sorry!!💥 The CODER_CONFIG_FILE provider_id: ``{provider_id}`` does not have the model_id: ``{model_id}`` in the ``models`` list.\n\nPlease check the environment variable: ``CODER_CONFIG_FILE`` file is at that path and is a valid coder.json file like the ``oats/config/coder.json``\n\nHere is the ``coder.json`` config dictionary:\n```\n{pp(config_dict)}\n```\n\nHere is the path to the current config:\n```\nexport CODER_CONFIG_FILE={coder_config_file}\n```\n'
            log.info(err_msg)
            raise Exception('Please fix the CODER_CONFIG_FILE for the logged error')
    if verbose:
        log.info(f'validated CODER_CONFIG_FILE for chat with provider_id: {provider_id} with model_id: {model_id}')
    return True

def main():
    """Standalone entry point: validate default providers and print status."""
    try:
        validate_coder_env(provider_id='vllm-small')
        log.info(f'### vLLM - chat - vllm-small - online ✔')
    except Exception:
        pass
    try:
        validate_coder_env(provider_id='t1')
        log.info(f'### vLLM - tool-calling - t1 - online ✔')
    except Exception:
        pass

if __name__ == '__main__':
    main()

