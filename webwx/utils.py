import re

EMOJI_DICT = {}
with open('webwx/emoji.txt') as f:
    for line in f:
        arr = line.strip().split(',')
        EMOJI_DICT[arr[0]] = arr[1]


def replace_emoji(text):
    def replace_func(match):
        if match:
            return EMOJI_DICT.get(match.group(1), '')

    replaced_text = re.sub(r'<span class="emoji emoji([a-zA-Z0-9]+)"></span>', replace_func, text)
    return replaced_text
