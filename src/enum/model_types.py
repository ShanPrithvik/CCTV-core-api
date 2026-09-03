from enum import Enum

class ModelType(Enum):
    CROWD_DETECTION = "CROWD_DETECTION"
    SHOPLIFTING = "SHOPLIFTING"
    RESTRICTED_AREA = "RESTRICTED_AREA"


    def __str__(self):
        return self.value
