OUTAGE_KEYWORDS = ["የኃይል አቅርቦት"]
INTERRUPTION_KEYWORDS = ["ቋረጥ"]


def is_outage_announcement(text: str) -> bool:
    if not text:
        return False
    has_outage_word = any(word in text for word in OUTAGE_KEYWORDS)
    has_interruption_word = any(word in text for word in INTERRUPTION_KEYWORDS)
    return has_outage_word and has_interruption_word


def extract_time_blocks(text: str) -> list:
    blocks = []
    current_time = None
    current_areas = []

    for line in text.split("\n"):
        line = line.strip()

        if line.startswith("✅"):
            if current_time is not None:
                blocks.append({"time": current_time, "areas": current_areas})
            current_time = line.replace("✅", "").strip()
            current_areas = []

        elif line.startswith("👉") and current_time is not None:
            cleaned = line.replace("👉", "").strip()
            parts = cleaned.split("፣")
            for part in parts:
                part = part.strip()
                part = part.replace("እና አካባቢው", "").strip()
                if part:
                    current_areas.append(part)

    if current_time is not None:
        blocks.append({"time": current_time, "areas": current_areas})

    return blocks


def extract_areas(text: str) -> list:
    all_areas = []
    for block in extract_time_blocks(text):
        all_areas.extend(block["areas"])
    return all_areas


def extract_date(text: str) -> str:
    for line in text.split("\n"):
        if "ቀን" in line:
            return line.strip()
    return ""