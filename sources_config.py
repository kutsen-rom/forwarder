INTERVAL = 600

SOURCES = {
    "BN": {
        "SOURCE": -1001146915409, 
        "KEYWORDS": ["Will List", "Will Add"]
        },
     "BB": {
        "SOURCE": -1001449478440, 
        "KEYWORDS": ["Coming Soon to"]
        },
     "RN1": {
        "SOURCE": -1002927278805, 
        "KEYWORDS": ["Coming Soon to"]
        },
     "RN2": {
        "SOURCE": -1002874216033, 
        "KEYWORDS": ["Coming Soon to"]
        }
    }

# Helper functions to get all sources and keywords
def get_all_sources():
    return [SOURCES[key]["SOURCE"] for key in SOURCES]

def get_all_keywords():
    all_keywords = []
    for key in SOURCES:
        all_keywords.extend(SOURCES[key]["KEYWORDS"])
    return list(set(all_keywords))  # Remove duplicates

def get_keywords_for_source(chat_id):
    for key in SOURCES:
        if SOURCES[key]["SOURCE"] == chat_id:
            return SOURCES[key]["KEYWORDS"]
    return []

def get_source_name(chat_id):
    for key in SOURCES:
        if SOURCES[key]["SOURCE"] == chat_id:
            return key
    return f"Chat {chat_id}"

# For backward compatibility
ALL_SOURCES = get_all_sources()
ALL_KEYWORDS = get_all_keywords()