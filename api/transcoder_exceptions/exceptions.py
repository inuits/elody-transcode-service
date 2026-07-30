from elody_types.types import MediafileEntity


class UnsupportedOperationException(Exception):
    def __init__(self, operation):
        message = f"Operation {operation} not supported"
        super().__init__(message)
        self.message = message


class FileDownloadRetryExhausted(Exception):
    def __init__(self, url: str, retries: int, exception: Exception):
        message = f"Failed to fully download {url} after {retries} retries. Last error: {exception}"
        super().__init__(message)
        self.message = message
        self.retries = retries
        self.exception = exception


class GetWidthHeightException(Exception):
    def __init__(self, mediafile: MediafileEntity):

        message = f"Could not get width and/or height from mediafile {mediafile['_id']}"
        super().__init__(message)
        self.message = message
