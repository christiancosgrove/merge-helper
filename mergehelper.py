#!/usr/bin/env python
# Setup: run `mv mergehelper.py /usr/local/bin/mergehelper`
# then run `mergehelper` in a git repo with merge conflicts
import multiprocessing
import os
import threading
import time
import openai
import sys
import re
from tqdm import tqdm

NUM_LINES_BEFORE = 5
NUM_LINES_AFTER = 5

def parse_git_status():
    """ Returns: list of merge conflicts [(filename, conflict)] """
    # stdin = sys.stdin.read()
    # print(stdin)

    # Instead of using stdin, just run git status and parse the output
    git_status = os.popen('git status').read()

    # TODO: Need to parse out list of file names "both modified" from after "Unmerged paths" section
    filenames = re.findall(r"both modified:   (.*)", git_status)

    # For each file name, get the contents of the file
    conflicts = []

    for filename in filenames:
        with open(filename, 'r') as f:
            # Read file lines
            lines = f.readlines()

            # Get (start, end) indices of merge conflicts
            conflict_indices = []
            curr_start = None
            for i, line in enumerate(lines):
                if line.startswith('<<<<<<<'):
                    curr_start = i
                elif line.startswith('>>>>>>>'):
                    conflict_indices.append((curr_start, i))
                    curr_start = None
            
            # Get line ranges for each merge conflict based on NUM_LINES_BEFORE and NUM_LINES_AFTER
            conflict_ranges = [(max(0, start - NUM_LINES_BEFORE), min(len(lines), end + NUM_LINES_AFTER)) for start, end in conflict_indices]

            # For each neighboring pair of conflicts (a, b), (c, d), if b > c
            for i in range(len(conflict_ranges) - 1):
                start1, end1 = conflict_ranges[i]
                start2, end2 = conflict_ranges[i + 1]
                if end1 > start2:
                    fair_middle = (conflict_indices[i][1] + conflict_indices[i + 1][0]) // 2
                    conflict_ranges[i] = (start1, fair_middle - 1)
                    conflict_ranges[i + 1] = (fair_middle, end2)

            # Get text for each merge conflict
            for (merge_start, merge_end), (range_start, range_end) in zip(conflict_indices, conflict_ranges):
                conflict = ''.join(lines[range_start:range_end])
                context_before = ''.join(lines[range_start:merge_start])
                context_after = ''.join(lines[merge_end:range_end])
                conflicts.append((filename, merge_start, merge_end, conflict, context_before, context_after))
    return conflicts

def colorize_conflict_text(conflict_text):
    # Format code before <<<<<< HEAD in green
    conflict_text = '\033[92m' + conflict_text.split('<<<<<<< HEAD')[0] + '\033[0m<<<<<<< HEAD' + conflict_text.split('<<<<<<< HEAD')[1]
    # Format first conflict in blue
    # Format second conflict in red
    conflict_text = re.sub(r'<<<<<<< HEAD', '<<<<<<< HEAD\033[94m', conflict_text)
    conflict_text = re.sub(r'=======', '\033[0m=======\033[91m', conflict_text)
    conflict_text = re.sub(r'>>>>>>>', '\033[0m>>>>>>>', conflict_text)

    # Format rest of code in green
    # Find occurrence of >>>>>>> in lines
    lines = conflict_text.splitlines()
    end_line_idx = [i for i, line in enumerate(lines) if line.startswith('\033[0m>>>>>>>')][0]
    lines[end_line_idx] = lines[end_line_idx] + '\033[92m'
    conflict_text = '\n'.join(lines) + '\033[0m'
    return conflict_text

def colorize_response(text):
    # Colorize ```...``` blocks green

    lines = text.splitlines()
    indices = [i for i, line in enumerate(lines) if line.startswith('```')]

    # For each pair of indices, colorize the text between them green
    for i in range(0, len(indices), 2):
        start, end = indices[i], indices[i + 1]
        # lines[start] = '\033[92m' + lines[start]
        # lines[end] = lines[end] + '\033[0m'
        # Only do in between
        lines[start + 1:end] = ['\033[92m' + line + '\033[0m' for line in lines[start + 1:end]]

    for i in range(len(indices)):
        lines[indices[i]] = ''
    
    return '\n'.join(lines)

def get_code(lines):
    code_block_indices = [i for i, line in enumerate(lines) if line.startswith('```')]
    code_start, code_end = code_block_indices[0], code_block_indices[-1]

    code = lines[code_start + 1:code_end]
    code = '\n'.join(code)

    return code


def parse_resolutions(response):
    lines = response.splitlines()

    indices = [i for i, line in enumerate(lines) if line.startswith('Resolution')]
    resolutions = [lines[i:j] for i, j in zip(indices, indices[1:] + [len(lines)])]

    out = []

    for resolution in resolutions:
        # code, explanation = get_code_and_explanation(resolution)
        code = get_code(resolution)
        out.append(code)
    
    # If we found no resolutions, then it's possible that there's just a single code block
    if len(out) == 0:
        code = get_code(lines)
        out.append(code)

    return out

def call_openai(conflict_text):
    engine = os.environ.get('OPENAI_ENGINE', 'gpt-4')
    retry_timeout = 1 # 1 second. Double every time.
    while True:
        try:
            completion = openai.ChatCompletion.create(
                model=engine,
                messages=[
                {"role": "system", "content": "You are a helpful assistant that helps users resolve merge conflicts."},
                {"role": "user", "content": f'This is a merge conflict:\n\n{conflict_text}\n\nPlease resolve the merge conflict if it is unambiguous. If the merge conflict is ambiguous, present two possible substitions for the <<<<<<< ... >>>>>>> block as "Resolution 1:\n```code```\nExplanation" and "Resolution 2:\n```code```\nExplanation".\n\nIMPORTANT: Do not include any code from before "<<<<<<<" in the resolutions.\n\nFinally, explain the implications of the changes in the context of the codebase.'}
                ], temperature=0.0
            )
            break
        except openai.error.RateLimitError as e:
            print(f'Rate limit error. Retrying in {retry_timeout} seconds.')
            time.sleep(retry_timeout)
            retry_timeout *= 2
            continue
    return completion.choices[0].message['content']

def call_openai_with_progress_bar(prompt):
    print(f'Calling {os.environ.get("OPENAI_ENGINE", "gpt-3.5-turbo")}')
    # Instead of using Thread, use multiprocessing.Pool with size 1
    pool = multiprocessing.Pool(processes=1)
    api_result = pool.apply_async(call_openai, (prompt,))

    while True:
        if not api_result.ready():
            print('.', end='')
            sys.stdout.flush()
            time.sleep(0.5)
        else:
            break
    
    print()
    return api_result.get()

def main():
    conflicts = parse_git_status()
    if len(conflicts) == 0:
        print("No merge conflicts found.")
        return
    
    for fname, _, _, conflict_text, context_before, context_after in conflicts:
        print(f"Merge conflict in {fname}:")
        print(colorize_conflict_text(conflict_text))
        print()

        response = call_openai_with_progress_bar(conflict_text)
        print(colorize_response(response))
        print()
        resolutions = parse_resolutions(response)

        # Get keyboard input from stdin, and validate
        while True:
            try:
                resolution_range = '1-' + str(len(resolutions)) if len(resolutions) > 1 else '1'
                user_input = input(f'Enter resolution ({resolution_range}), or "n" for none: ')
                if user_input == 'n':
                    break
                user_input = int(user_input)
                if user_input < 1 or user_input > len(resolutions):
                    raise ValueError
                break
            except ValueError:
                print('Invalid input. Please enter a number between 1 and', len(resolutions), 'or "n".')
        if user_input == 'n':
            print('Not applying any resolution. Please manually resolve the merge conflict.')
        else:
            # Apply the resolution by replacing the conflict text with the code from the resolution
            code = resolutions[user_input - 1]

            # Get just the lines of the conflict from `conflict_text`
            lines = conflict_text.splitlines()
            conflict_lines = lines[[i for i, line in enumerate(lines) if line.startswith('<<<<<<< HEAD')][0]: [i for i, line in enumerate(lines) if line.startswith('>>>>>>>')][0] + 1]
            with open(fname, 'r') as f:
                contents = f.read()
            contents = contents.replace('\n'.join(conflict_lines), code)


            # Deduplicate context lines. If the code block begins with context_before, then remove context_before from the code block.
            if code.startswith(context_before):
                code = code[len(context_before):]
            if code.endswith(context_after):
                code = code[:-len(context_after)]

            with open(fname, 'w') as f:
                f.write(contents)
            print('Applied resolution', user_input)
        print()


if __name__ == '__main__':
    main()
