from enum import StrEnum


class TaskType(StrEnum):
    FETCH = "fetch"
    EXECUTE = "execute"
    DELIVER = "deliver"
    PR_FEEDBACK = "pr_feedback"
    TRACKER_FEEDBACK = "tracker_feedback"


class TaskStatus(StrEnum):
    NEW = "new"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


TASK_TYPE_VALUES = tuple(task_type.value for task_type in TaskType)
TASK_STATUS_VALUES = tuple(status.value for status in TaskStatus)


__all__ = [
    "TASK_STATUS_VALUES",
    "TASK_TYPE_VALUES",
    "TaskStatus",
    "TaskType",
]
