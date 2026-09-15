OUTAGE_KEYWORDS = ["የኃይል አቅርቦት"]
INTERRUPTION_KEYWORDS = ["ቋረጥ"]

AREA_ALIASES = {
    "bole": ["ቦሌ", "bole"],
    "ቦሌ": ["ቦሌ", "bole"],
    "wingate": ["ዊንጌት", "wingate"],
    "ዊንጌት": ["ዊንጌት", "wingate"],
    "piassa": ["ፒያሳ", "piassa", "piazza"],
    "piazza": ["ፒያሳ", "piassa", "piazza"],
    "ፒያሳ": ["ፒያሳ", "piassa", "piazza"],
    "megenagna": ["መገናኛ", "megenagna"],
    "መገናኛ": ["መገናኛ", "megenagna"],
    "koye": ["ኮዬ", "koye"],
    "ኮዬ": ["ኮዬ", "koye"],
    "alembank": ["አለምባንክ", "alembank"],
    "አለምባንክ": ["አለምባንክ", "alembank"],
    "bethel": ["ቤተል", "bethel"],
    "ቤተል": ["ቤተል", "bethel"],
    "bello": ["ቤላ", "bello", "bella"],
    "ቤላ": ["ቤላ", "bello", "bella"],
    "sebeta": ["ሰበታ", "sebeta"],
    "ሰበታ": ["ሰበታ", "sebeta"],
    "alemgena": ["አለምገና", "ዓለምገና", "alemgena"],
    "አለምገና": ["አለምገና", "ዓለምገና", "alemgena"],
    "ዓለምገና": ["አለምገና", "ዓለምገና", "alemgena"],
}


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
        line = line.replace("\xa0", " ").replace("\ufeff", "").strip()

        if "✅" in line:
            if current_time is not None and (current_time or current_areas):
                blocks.append({"time": current_time, "areas": current_areas})
            current_time = line.replace("✅", "").strip()
            current_areas = []

        elif "👉" in line and current_time is not None:
            cleaned = line.replace("👉", "").strip()
            parts = cleaned.replace(",", "፣").split("፣")
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


def is_area_match(user_location: str, target_area: str) -> bool:
    if not user_location or not target_area:
        return False

    u_loc = user_location.strip().lower()
    t_area = target_area.strip().lower()

    if u_loc in t_area or t_area in u_loc:
        return True

    user_aliases = AREA_ALIASES.get(u_loc, [u_loc])
    for alias in user_aliases:
        if alias.lower() in t_area or t_area in alias.lower():
            return True

    target_aliases = AREA_ALIASES.get(t_area, [t_area])
    for t_alias in target_aliases:
        if u_loc in t_alias.lower() or t_alias.lower() in u_loc:
            return True

    return False