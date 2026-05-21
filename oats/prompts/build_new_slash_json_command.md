# Goal
You are an expert software engineer at programming.

# Objective
Build a new slash command for the oats interactive CLI that reads and displays JSON files.

# Steps
1) review: ./oats/cli/interactive.py
2) review the /config command in the interactive.py
3) add a new cmd that matches == '/json' that read a json file from s3 or locally. Add this as a new module called: ./oats/cli/cmd/slash_json_command.py. This new module must support Example usage:
./slash_json_commands.py -f JSON_FILE
4) Add support for argparse short arguments.
5) Add the coder.log from the existing log.py file.
6) Use a helper method for main.
