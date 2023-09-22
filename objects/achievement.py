class Achievement:
    def __init__(self, **kwargs) -> None:
        self.id: int = kwargs.get("id", 0)
        self.name: str = kwargs.get("name", "")
        self.description: str = kwargs.get("description", "")
        self.icon: str = kwargs.get("icon", "")
        self.condition: str = kwargs.get("condition", "")

    def __str__(self) -> str:
        return f"{self.icon}+{self.name}+{self.description}"
