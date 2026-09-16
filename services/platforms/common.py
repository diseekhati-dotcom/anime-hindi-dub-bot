import re

LANGS = ["Japanese", "English", "Hindi", "Tamil", "Telugu", "Korean", "Chinese", "Spanish", "French", "German"]

def clean_language_list(text):
    found = []
    for lang in LANGS:
        if re.search(rf"\b{re.escape(lang)}\b", text, re.I):
            found.append(lang)
    return found
