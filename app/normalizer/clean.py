import re



def clean_body(text: str) -> str:
    if not text:
        return ""

    text = re.sub(r"```[\s\S]*?```", "[CODE]", text)
    text = re.sub(r"`[^`]+`", "[INLINE_CODE]", text)
    text = re.sub(r"https?://\S+", "[URL]", text)
    return " ".join(text.split())
