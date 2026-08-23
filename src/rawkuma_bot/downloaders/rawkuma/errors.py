class RawkumaError(RuntimeError):
    """Base error for expected Rawkuma failures."""


class InvalidRawkumaURL(RawkumaError):
    pass


class MangaNotFound(RawkumaError):
    pass


class ChapterNotFound(RawkumaError):
    pass


class ImagesNotFound(RawkumaError):
    pass


class NetworkError(RawkumaError):
    pass


class DownloadFailed(RawkumaError):
    pass


class SourceUnavailable(RawkumaError):
    pass
