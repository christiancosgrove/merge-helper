#
import openai
import sys
import re

NUM_LINES_BEFORE = 1
NUM_LINES_AFTER = 1

def parse_stdin():
    """ Returns: list of merge conflicts [(filename, conflict)] """
    stdin = sys.stdin.read()

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

    filenames = re.findall(r"both modified:   (.*)", stdin)
    print("FILENAMES", filenames)

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
            for start, end in conflict_ranges:
                conflict = ''.join(lines[start:end])
                conflicts.append((filename, conflict))
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

# match up to 3 lines in regex:
def main():
    # print(parse_stdin())
    for fname, conflict_text in parse_stdin():
        print(colorize_conflict_text(conflict_text))

if __name__ == '__main__':
    main()