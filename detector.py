OUTAGE_KEYWORDS = ["የኃይል አቅርቦት"]
INTERRUPTION_KEYWORDS = ["ቋረጥ"]

AREA_ALIASES = {
    "bole": ["ቦሌ", "bole"],
    "ቦሌ": ["ቦሌ", "bole"],
    "wingate": ["ዊንጌት", "ዊን ጌት", "wingate"],
    "ዊንጌት": ["ዊንጌት", "ዊን ጌት", "wingate"],
    "piassa": ["ፒያሳ", "piassa", "piazza"],
    "piazza": ["ፒያሳ", "piassa", "piazza"],
    "ፒያሳ": ["ፒያሳ", "piassa", "piazza"],
    "megenagna": ["መገናኛ", "megenagna"],
    "መገናኛ": ["መገናኛ", "megenagna"],
    "koye": ["ኮዬ", "koye"],
    "ኮዬ": ["ኮዬ", "koye"],
    "alembank": ["አለምባንክ", "አለም ባንክ", "ዓለም ባንክ", "alembank"],
    "አለምባንክ": ["አለምባንክ", "አለም ባንክ", "ዓለም ባንክ", "alembank"],
    "አለም ባንክ": ["አለምባንክ", "አለም ባንክ", "ዓለም ባንክ", "alembank"],
    "bethel": ["ቤተል", "ቤቴል", "bethel"],
    "ቤተል": ["ቤተል", "ቤቴል", "bethel"],
    "bello": ["ቤላ", "bello", "bella"],
    "ቤላ": ["ቤላ", "bello", "bella"],
    "sebeta": ["ሰበታ", "sebeta"],
    "ሰበታ": ["ሰበታ", "sebeta"],
    "alemgena": ["አለምገና", "ዓለምገና", "አለም ገና", "alemgena"],
    "አለምገና": ["አለምገና", "ዓለምገና", "አለም ገና", "alemgena"],
    "ዓለምገና": ["አለምገና", "ዓለምገና", "አለም ገና", "alemgena"],
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

    u_raw = user_location.strip().lower()
    t_raw = target_area.strip().lower()

    u_norm = u_raw.replace(" ", "")
    t_norm = t_raw.replace(" ", "")

    if u_raw in t_raw or t_raw in u_raw or u_norm in t_norm or t_norm in u_norm:
        return True

    user_aliases = AREA_ALIASES.get(u_raw, [u_raw])
    for alias in user_aliases:
        a_raw = alias.strip().lower()
        a_norm = a_raw.replace(" ", "")
        if a_raw in t_raw or t_raw in a_raw or a_norm in t_norm or t_norm in a_norm:
            return True

    target_aliases = AREA_ALIASES.get(t_raw, [t_raw])
    for t_alias in target_aliases:
        a_raw = t_alias.strip().lower()
        a_norm = a_raw.replace(" ", "")
        if u_raw in a_raw or a_raw in u_raw or u_norm in a_norm or a_norm in u_norm:
            return True

    return False