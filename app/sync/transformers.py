class Transformer:
    def to_canonical(self, value, source: str):
        return value

    def from_canonical(self, value, target: str):
        return value


class StateTransformer(Transformer):
    def __init__(self, jira_map: dict[str, str] | None = None):
        self.jira_map = jira_map or {}

    def to_canonical(self, value, source: str):
        if source == "jira":
            return self.jira_map.get(str(value), "open")
        return str(value)

    def from_canonical(self, value, target: str):
        if target == "jira":
            # fallback mapping for unknown projects
            if str(value) == "closed":
                return "Done"
            return "To Do"
        return value
