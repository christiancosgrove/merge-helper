#
import os
import time
import openai
import sys
import re

NUM_LINES_BEFORE = 1
NUM_LINES_AFTER = 1

def parse_git_status():
    """ Returns: list of merge conflicts [(filename, conflict)] """
    # stdin = sys.stdin.read()
    # print(stdin)

    # Instead of using stdin, just run git status and parse the output
    git_status = os.popen('git status').read()

    # Example:
    """On branch main
You have unmerged paths.
  (fix conflicts and run "git commit")
  (use "git merge --abort" to abort the merge)

Unmerged paths:
  (use "git add <file>..." to mark resolution)
        both modified:   test.py

no changes added to commit (use "git add" and/or "git commit -a")"""
    # Need to parse out list of file names "both modified" from after "Unmerged paths" section

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
                conflicts.append((filename, merge_start, merge_end, conflict))
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

    # Get all lines
    lines = text.splitlines()

    # Get all lines beginning with "```"
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

def get_code_and_explanation(lines):
    # Get the code block indices, which are the first and last lines that start with "```"
    code_block_indices = [i for i, line in enumerate(lines) if line.startswith('```')]
    code_start, code_end = code_block_indices[0], code_block_indices[-1]

    # Get the text between the code block indices
    code = lines[code_start + 1:code_end]
    # Join
    code = '\n'.join(code)

    # Get the explanation text, which runs from the first line that starts with "Explanation" to the end
    explanation_start = [i for i, line in enumerate(lines) if line.startswith('Explanation')][0]
    explanation = lines[explanation_start:]
    # Join
    explanation = '\n'.join(explanation)

    return code, explanation

def parse_resolutions(response):
    lines = response.splitlines()

    # Get all lines starting with "Resolution"
    indices = [i for i, line in enumerate(lines) if line.startswith('Resolution')]

    # Get text between each pair of indices
    resolutions = [lines[i:j] for i, j in zip(indices, indices[1:] + [len(lines)])]

    out = []

    for resolution in resolutions:
        code, explanation = get_code_and_explanation(resolution)
        out.append((code, explanation))
    
    # If we found no resolutions, then it's possible that there's just a single code block
    if len(out) == 0:
        code, explanation = get_code_and_explanation(lines)
        out.append((code, explanation))

    return out

# match up to 3 lines in regex:
def main():
    engine = os.environ.get('OPENAI_ENGINE', 'gpt-3.5-turbo')
    conflicts = parse_git_status()
    if len(conflicts) == 0:
        print("No merge conflicts found.")
        return
    
    for fname, _, _, conflict_text in conflicts:
        print(f"Merge conflict in {fname}:")
        print(colorize_conflict_text(conflict_text))
        print()
        # Call the OpenAI API to get suggestions with prompt.
        completion = openai.ChatCompletion.create(
          model=engine,
          messages=[
            {"role": "system", "content": "You are a helpful assistant that helps users resolve merge conflicts."},
            {"role": "user", "content": f'Below is an example of a merge conflict. Please resolve the merge conflict if it is unambiguous. If the merge conflict is ambiguous, present two possible substitions for the <<<<<<< ... >>>>>>> block as "Resolution 1:\n```code```\nExplanation" and "Resolution 2:\n```code```\nExplanation". Do not include any code from the context in the resolutions. Explain the implications of the changes in the context of the codebase.\n\n{conflict_text}'}
          ], temperature=0
        )
        # print(completion.choices[0].message)
        response = completion.choices[0].message['content']
        print(colorize_response(response))
        resolutions = parse_resolutions(response)

        # Get keyboard input from stdin, and validate
        while True:
            try:
                user_input = input('Enter resolution (1-' + str(len(resolutions)) + '), or "n" for none: ')
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
            code, _ = resolutions[user_input - 1]

            # Get just the lines of the conflict from `conflict_text`
            lines = conflict_text.splitlines()
            conflict_lines = lines[[i for i, line in enumerate(lines) if line.startswith('<<<<<<< HEAD')][0]: [i for i, line in enumerate(lines) if line.startswith('>>>>>>>')][0] + 1]
            with open(fname, 'r') as f:
                contents = f.read()
            contents = contents.replace('\n'.join(conflict_lines), code)
            with open(fname, 'w') as f:
                f.write(contents)
            print('Applied resolution', user_input)
        print()


if __name__ == '__main__':
    main()