from backend.composition import RuntimeContainer, create_runtime_container


def run() -> RuntimeContainer:
    return create_runtime_container()
