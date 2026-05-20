"""Data models for the OAT (Open Agent Tools) system."""
import heapq
import os
import re
import ujson as json
from typing import List, Tuple
from pydantic import BaseModel
from rank_bm25 import BM25Okapi
from oats.pp import pp
from oats.log import gl

log = gl('oats.models')

class OatPromptChoices(BaseModel):
    """Container for tool-choice results returned by the OAT index."""
    status: bool = False
    actions: list[str] = []
    prompts: list[str] = []
    src_files: list[str] = []
    partial_actions: list[str] = []
    partial_prompts: list[str] = []
    partial_src_files: list[str] = []
    index_files: list[str] = []
    tool_data: dict = {}
    version: str = '9'

class OatConfig(BaseModel):
    """Configuration and index data for OAT tool resolution."""
    repo_uses_index: str = os.getenv("CODER_TOOL_USES_INDEX", "./.ai/AGENT.repo_uses.python.tools.json")
    repo_uses_data: dict = {}
    repo_uses_actions: list = []
    repo_uses_prompts: list = []
    repo_uses_src_files: list = []
    repo_uses_action_to_src_dict: dict = {}
    repo_uses_prompt_dict: dict = {}
    best_tools: list[dict] = []
    best_impls: dict = {}

    def __init__(self, **kwargs):
        """Load the OAT index file and build action/prompt lookup dictionaries."""
        super().__init__(**kwargs)
        self.best_tools = {}
        self.best_impls = {}
        if os.path.exists(self.repo_uses_index):
            with open(self.repo_uses_index, 'r') as f:
                self.repo_uses_data = json.loads(f.read())
        if len(self.repo_uses_data) > 0:
            for src_file in self.repo_uses_data:
                for use_key in self.repo_uses_data[src_file]:
                    action_str = use_key
                    src_prompt = self.repo_uses_data[src_file][use_key]
                    self.repo_uses_actions.append(action_str)
                    self.repo_uses_prompts.append(src_prompt)
                    if action_str not in self.repo_uses_action_to_src_dict:
                        self.repo_uses_action_to_src_dict[action_str] = []
                    if action_str not in self.repo_uses_prompt_dict:
                        self.repo_uses_prompt_dict[action_str] = []
                    self.repo_uses_action_to_src_dict[action_str].append(src_file)
                    self.repo_uses_prompt_dict[action_str].append(src_prompt)
    
    def get_prompt_choices(self, prompt: str, verbose: bool = False) -> OatPromptChoices:
        """Find tool matches for a prompt using exact and partial string matching."""
        choices = OatPromptChoices()
        choices.status = False
        prompt_splits = prompt.split(' ')
        first_prompt = None
        second_prompt = None
        third_prompt = None
        first_prompt = None
        num_words = len(prompt_splits)
        all_prompts = []
        found_prompts = {}
        if num_words >= 1:
            all_prompts.insert(0, '_'.join(prompt_splits[:1]).lower())
        if num_words >= 2:
            all_prompts.insert(0, '_'.join(prompt_splits[:2]).lower())
        if num_words >= 3:
            all_prompts.insert(0, '_'.join(prompt_splits[:3]).lower())
        if num_words >= 4:
            all_prompts.insert(0, '_'.join(prompt_splits[:4]).lower())
        if num_words == 0:
            log.error(f'no_words_found_in_prompt_to_check: {prompt}')
            return choices
        valid_match = False
        choices.status = False
        src_files = []
        best_files = []
        best_uses = {}
        tool_results = []
        use_prompts = []
        actions = []
        self.best_tools = {}
        self.best_impls = {}
        for check_prompt in all_prompts:
            if check_prompt == '':
                continue
            if check_prompt in self.repo_uses_action_to_src_dict:
                if check_prompt in self.repo_uses_prompt_dict:
                    if check_prompt not in found_prompts:
                        found_prompts[check_prompt] = self.repo_uses_action_to_src_dict[check_prompt]
                    else:
                        continue
                    actions.append(check_prompt)
                    valid_match = True
                    for full_prompt in self.repo_uses_prompt_dict[check_prompt]:
                        use_prompts.append(full_prompt)
                    for src_file in self.repo_uses_action_to_src_dict[check_prompt]:
                        src_files.append(src_file)
                        if src_file not in best_uses:
                            best_files.append(src_file)
                            best_uses[src_file] = self.repo_uses_data[src_file]
                            new_tool_def = {
                                "file": src_file,
                                "func": check_prompt,
                                "description": best_uses[src_file][check_prompt],
                                "score": float(f'{1.0 - (0.1 * len(tool_results)):0.2f}'),
                                "retrieval_score": 1.0,
                            }
                            tool_results.append(new_tool_def)
                else:
                    log.error(f'missing_prompt_dict_check_prompt: {check_prompt[0:32]}')
            else:
                if verbose:
                    log.error(f'missing_action_to_src_dict: {check_prompt[0:32]}')
        if len(actions) < 2:
            skip_words = [
                'build',
                'create',
                'review',
                'get',
                'delete'
                # 'prune',
                # 'retrieve',
                'think',
                # 'wonder',
                'walk',
                'check',
                # 'estimate',
                # 'find',
                # 'search',
                # 'query',
                'read',
                'view',
                'gets',
                'assemble',
                'compile',
                'built',
                'to',
                'the',
                'it',
                'a'
                'inspect',
                'curate',
                'analyze',
                'process',
                'handle',
                'examine',
                'test',
                'text',
                'name',
                'user',
                'person'
                'api',
                'helper',
                'list',
                'select',
                'take',
                'took',
                'red',
                'blue',
                'green'
                'yellow',
                'orange',
            ]
            for action in self.repo_uses_action_to_src_dict:
                for check_prompt in all_prompts:
                    if check_prompt == '':
                        continue
                    if check_prompt in skip_words:
                        continue
                    lower_prompt = check_prompt.lower()
                    # print(check_prompt)
                    if lower_prompt in action:
                        if action in self.repo_uses_prompt_dict:
                            if action not in found_prompts:
                                # found_prompts[action] = self.repo_uses_prompts[action]
                                found_prompts[action] = self.repo_uses_prompt_dict[action]
                            else:
                                continue
                            check_value = self.repo_uses_prompt_dict[action]
                            if verbose:
                                log.info(f'# Source action: {action} check_prompt:\n```\n{check_prompt}\n```\ncheck_value\n```\n{check_value}\n```\n')
                            actions.append(check_prompt)
                            for src_file in self.repo_uses_action_to_src_dict[action]:
                                src_files.append(src_file)
                                if src_file not in best_uses:
                                    best_files.append(src_file)
                                    best_uses[src_file] = self.repo_uses_data[src_file]
                                    use_func = ''
                                    use_desc = ''
                                    for comp_prompt, comp_desc in best_uses[src_file].items():
                                        if lower_prompt in comp_prompt:
                                            use_func = comp_prompt
                                            use_desc = comp_desc
                                            break
                                    if use_func == '':
                                        use_func = list(best_uses[src_file].items())[0][0]
                                        use_desc = best_uses[src_file][use_func]
                                        log.debug('-----\nstart:\n')
                                    new_tool_def = {
                                        "file": src_file,
                                        "func": use_func,
                                        "description": use_desc,
                                        "score": float(f'{1.0 - (0.1 * len(tool_results)):0.2f}'),
                                        "retrieval_score": 1.0,
                                    }
                                    tool_results.append(new_tool_def)
                                    # if len(tool_results) > 1:
                                    #     print(pp(tool_results)
                                    #     STOP_TOOL_TEST_1
                            # print(found_prompts)
                            found_prompts['src_files'] = src_files
                            # print(src_files)
                            valid_match = True
                            for full_prompt in self.repo_uses_prompt_dict[action]:
                                use_prompts.append(full_prompt)
                        else:
                            log.error(f'missing_partial_prompt_dict_check_prompt: {action[0:32]}')
                    # else:
                    #    log.error(f'missing_partial_action_in_check_prompt action: {action} prompt: {check_prompt[0:32]}')

        if len(src_files) == 0:
            choices.status = False
        else:
            choices.status = True
        choices.actions = actions[0:10]
        choices.prompts = use_prompts[0:10]
        choices.src_files = src_files[0:10]
        choices.index_files.append(self.repo_uses_index)
        model = 'bm25'
        tool_data = {
            "query": prompt,
            "model": model,
            "reranked": False,
            "best_files": best_files,
            "best_uses": best_uses,
            "results": tool_results,
        }
        if verbose:
            log.info(f'# Prompt Choice Report')
            log.debug('best_uses:')
            print(pp(best_uses))
            log.debug('tool_results:')
            print(pp(tool_results))
        """
        # create best_impls
        for tool_node in tool_results:
            src_file = tool_node['file']
            func_name = tool_node['func']
            description = tool_node['description']
            score = tool_node['score']
            rscore = tool_node['retrieval_score']
        """
        choices.tool_data = tool_data
        return choices

    def get_best_matches_bm25(self, prompt: str, top_k: int = 5, verbose: bool = False) -> OatPromptChoices:
        """Use BM25 to find the best matching actions for a given prompt.

        Compares the prompt against each key in repo_uses_action_to_src_dict
        and returns the top_k best matches sorted by BM25 score.
        """
        choices = OatPromptChoices()
        choices.status = False

        if not self.repo_uses_action_to_src_dict:
            if verbose:
                log.error('repo_uses_action_to_src_dict is empty — nothing to match against')
            return choices

        # Build corpus: one entry per action key
        actions_list = list(self.repo_uses_action_to_src_dict.keys())
        # Tokenize: split on underscores and whitespace so that
        # "post_message_to_channel" and "post message to channel" match.
        tokenized_corpus = [re.split(r'[\s_]+', action.lower()) for action in actions_list]
        tokenized_query = re.split(r'[\s_]+', prompt.lower())

        if not tokenized_query:
            log.error(f'no tokens in prompt for bm25: {prompt}')
            return choices

        # Build BM25 index
        bm25 = BM25Okapi(tokenized_corpus)

        # Score query against all actions
        scores = bm25.get_scores(tokenized_query)

        # Get top_k indices sorted by descending score
        top_indices = heapq.nlargest(top_k, range(len(scores)), key=lambda i: scores[i])

        # Filter out zero-score results
        top_indices = [i for i in top_indices if scores[i] > 0]

        if not top_indices:
            if verbose:
                log.info(f'### Sorry!! no bm25 matches found for prompt: {prompt[:64]}')
            return choices

        choices.status = True
        src_files: List[str] = []
        use_prompts: List[str] = []
        actions = []

        for idx in top_indices:
            action = actions_list[idx]
            choices.actions.append(action)
            # Collect associated source files
            for src_file in self.repo_uses_action_to_src_dict[action]:
                if src_file not in src_files:
                    src_files.append(src_file)
            # Collect associated prompts
            if action in self.repo_uses_prompt_dict:
                for full_prompt in self.repo_uses_prompt_dict[action]:
                    if full_prompt not in use_prompts:
                        use_prompts.append(full_prompt)

        if len(src_files) == 0:
            choices.status = False
        else:
            choices.status = True
        choices.prompts = use_prompts[0:10]
        choices.src_files = src_files[0:10]
        choices.index_files.append(self.repo_uses_index)
        return choices
