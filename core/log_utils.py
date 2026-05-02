import logging

_op_logger = logging.getLogger("lit-critic")

def op_start(operation: str, file: str) -> None:
    _op_logger.info("%s | %s | starting", operation, file)

def op_complete(operation: str, file: str, **results) -> None:
    if results:
        result_str = ", ".join(f"{k}={v}" for k, v in results.items())
        _op_logger.info("%s | %s | completed -- results: %s", operation, file, result_str)
    else:
        _op_logger.info("%s | %s | completed", operation, file)
