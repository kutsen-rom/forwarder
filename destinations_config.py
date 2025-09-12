INTERVAL_MINUTES = 7

# Limit of how many previous messages to check
LAST_MESSAGES_LIMIT = 20

# I can use multiple destinations and specify different sources with their own set of keywords
DESTINATIONS = {
    "NLA": {
        "DESTINATION": -1002972933415,
        "SOURCES": {
            "BN": {"SOURCE": -1001146915409, "KEYWORDS": ["Will List", "Will Add"]},
            "BNA": {
                "SOURCE": -1002450025950,
                "KEYWORDS": ["is the first platform to", "Token Circulation"],
            },
            "BB": {"SOURCE": -1001449478440, "KEYWORDS": ["Coming Soon to"]},
            # Testing sources
            "TEST_1": {"SOURCE": -1002927278805, "KEYWORDS": ["Coming Soon to"]},
            "TEST_2": {"SOURCE": -1002874216033, "KEYWORDS": ["keyword1"]},
        },
    },
}


# Get all source IDs across all destinations
def get_all_sources():
    sources = []
    for dest in DESTINATIONS.values():
        for src in dest["SOURCES"].values():
            sources.append(src["SOURCE"])
    return sources


# Get all destination IDs
def get_all_destinations():
    return [dest["DESTINATION"] for dest in DESTINATIONS.values()]


# Get all unique keywords across all sources
def get_all_keywords():
    keywords = set()
    for dest in DESTINATIONS.values():
        for src in dest["SOURCES"].values():
            keywords.update(src["KEYWORDS"])
    return list(keywords)


# Get keywords for a specific source by chat_id
def get_keywords_for_source(chat_id):
    for dest in DESTINATIONS.values():
        for src in dest["SOURCES"].values():
            if src["SOURCE"] == chat_id:
                return src["KEYWORDS"]
    return []


# Get source name (e.g. BN, BB) by chat_id
def get_source_name(chat_id):
    for dest in DESTINATIONS.values():
        for name, src in dest["SOURCES"].items():
            if src["SOURCE"] == chat_id:
                return name
    return f"Chat {chat_id}"
