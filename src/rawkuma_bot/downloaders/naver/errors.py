class NaverError(RuntimeError):
    """Base error for expected Naver failures."""


class InvalidNaverURL(NaverError):
    pass


class MangaNotFound(NaverError):
    pass


class ChapterNotFound(NaverError):
    pass


class ImagesNotFound(NaverError):
    pass


class NetworkError(NaverError):
    pass


class DownloadFailed(NaverError):
    pass


class SourceUnavailable(NaverError):
    pass
