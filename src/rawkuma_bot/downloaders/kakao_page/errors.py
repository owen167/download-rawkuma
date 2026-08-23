class KakaoPageError(RuntimeError):
    """Base error for expected Kakao Page failures."""


class InvalidKakaoPageURL(KakaoPageError):
    pass


class MangaNotFound(KakaoPageError):
    pass


class ChapterNotFound(KakaoPageError):
    pass


class ProductNotReadable(KakaoPageError):
    pass


class ContentNotFound(KakaoPageError):
    pass


class NetworkError(KakaoPageError):
    pass


class DownloadFailed(KakaoPageError):
    pass
